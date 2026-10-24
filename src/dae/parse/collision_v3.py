"""Dagor V3 collision geometry decoder (class id 0xACE50000, version bits in low word).

War Thunder now stores collision geometry with the magic ``0xACE50003``: the data
that follows the 4 byte magic is compressed and, once decompressed, uses the
streaming ``CollResStreamHeader`` layout instead of the flat nodes used before.

Only the geometry (vertex positions and triangle indices) is decoded here - the
memory image of the BVH is not reconstructed.  Format details:

  * outer block: <u32 magic><u24 compressed size><u8 method><payload>
    method 0x40 = zstd, 0x60 = zlib, 0x20 = lzma, 0x80 = oodle
  * stream: 108 byte header, then per-node bind records, node records,
    transforms and finally the BLAS chunks, physics material pool, capsules,
    convex planes and the name tables
  * BLAS chunk: 36 byte quantisation frame + <BlasIoHeader><verts><wire tree>
  * wire tree elements start with a 1 byte marker: 0x00 full leaf,
    0xFE/0xFD short leaf, 0xFF raw leaf, 1..252 internal node with N children
"""

from struct import unpack, unpack_from
from zlib import decompress as _zlibDecompress

COLLISION_CLASS_ID = 0xACE50000
COLLISION_CLASS_MASK = 0xFFFF0000

STREAM_HEADER_SIZE = 108
BIND_REC_SIZE = 8
NODE_REC_SIZE = 48
MATRIX_SIZE = 48

CHUNK_FRAME_SIZE = 36
BLAS_IO_HEADER_SIZE = 40
BLAS_IO_MAGIC = 0x694C4264

QUAD_LEAF_FLAG = 1 << 31
QUAD_FLIPA_FLAG = 1 << 29
QUAD_FLIPB_FLAG = 1 << 30

RAW_LEAF_MARKER = 0xFF
SHORT_LEAF_MARKER = 0xFE
SHORT_LEAF_FLIP_MARKER = 0xFD
MAX_CHILD_COUNT = SHORT_LEAF_FLIP_MARKER - 1
MAX_TREE_DEPTH = 256

# stackless sizes used only to follow the forest stop condition
STACKLESS_LEAF_SIZE = 28
STACKLESS_NODE_SIZE = 16

# CollisionResourceNodeType
NODE_TYPE_MESH = 0


def isV3(magic:int):
	return (magic & COLLISION_CLASS_MASK) == COLLISION_CLASS_ID and (magic & 0xFFFF) != 0


def decompressBlock(block:bytes):
	"""Decompress the payload that follows the 4 byte magic.

	``block`` starts at the compressed size (the caller already consumed the
	magic).  Raises ValueError when the compression method is unsupported.
	"""

	if len(block) < 4:
		raise ValueError("Truncated collision compression header")
	cSz = int.from_bytes(block[0:3], "little")
	cMethod = block[3]
	if cSz > len(block) - 4:
		raise ValueError("Truncated collision payload")
	payload = block[4:4 + cSz]

	if cMethod == 0:
		return payload

	if cMethod == 0x80:
		from util.decompression import oodleDecompress
		return oodleDecompress(payload)

	if cMethod == 0x40:
		import zstandard

		return zstandard.ZstdDecompressor().decompress(payload)

	if cMethod == 0x60:
		return _zlibDecompress(payload)

	if cMethod == 0x20:
		import lzma

		return lzma.decompress(payload, format = lzma.FORMAT_ALONE)

	raise ValueError(f"Unsupported collision compression method {hex(cMethod)}")


def _signExtend13(value:int):
	value &= 0x1FFF

	return value - 0x2000 if value & 0x1000 else value


def _unpackVert21(data:bytes, ofs:int):
	v = unpack_from("<Q", data, ofs)[0]

	return (
		(v & 0x1FFFFF) / 32.0,
		((v >> 21) & 0x1FFFFF) / 32.0,
		((v >> 42) & 0x1FFFFF) / 32.0)


def _transformVertex(tm, v):
	# Dagor TMatrix: column major - t[0..2] = col0, t[3..5] = col1, t[6..8] = col2,
	# t[9..11] = translation.  result = M * v + T

	return (
		tm[0] * v[0] + tm[3] * v[1] + tm[6] * v[2] + tm[9],
		tm[1] * v[0] + tm[4] * v[1] + tm[7] * v[2] + tm[10],
		tm[2] * v[0] + tm[5] * v[1] + tm[8] * v[2] + tm[11])


def _decodeLeafFaces(w0:int, w1:int, w2:int, w3:int, vertCount:int):
	"""Expand the double-quad words of one leaf into triangles.

	On the wire W1 holds the apex vertex index in bits 0..23 (the runtime format
	stores a byte offset shifted by two instead).
	"""

	base = w1 & 0xFFFFFF

	o1 = _signExtend13(w0)
	o2 = _signExtend13(w0 >> 13)
	o3 = _signExtend13(((w0 >> 26) & 0x1F) | (((w1 >> 24) & 0xFF) << 5))

	deltaB = w2 & 0xFFFF
	o1B = _signExtend13(w2 >> 16)
	o2B = _signExtend13(w3)
	o3B = _signExtend13(w3 >> 13)

	flipA = bool(w2 & QUAD_FLIPA_FLAG)
	flipB = bool(w2 & QUAD_FLIPB_FLAG)

	singleA = o3 == o2
	hasB = o1B != o2B
	singleB = o3B == o2B

	def valid(idx:int):
		return 0 <= idx < vertCount

	indices = [base, base + o1, base + o2]

	if not singleA:
		indices.append(base + o3)

	if hasB:
		baseB = base + deltaB
		indices.extend((baseB, baseB + o1B, baseB + o2B))

		if not singleB:
			indices.append(baseB + o3B)

	# a leaf whose indices do not fit the vertex range is garbage, skip it
	if not all(valid(idx) for idx in indices):
		return []

	faces = [(base, base + o1, base + o2)]

	if not singleA:
		if flipA:
			faces.append((base + o2, base + o1, base + o3))
		else:
			faces.append((base + o1, base + o2, base + o3))

	if hasB:
		baseB = base + deltaB
		faces.append((baseB, baseB + o1B, baseB + o2B))

		if not singleB:
			if flipB:
				faces.append((baseB + o2B, baseB + o1B, baseB + o3B))
			else:
				faces.append((baseB + o1B, baseB + o2B, baseB + o3B))

	return faces


def _parseWireTree(data:bytes, vertCount:int, stacklessSize:int):
	"""Walk the compact wire BVH and collect the triangles of every leaf."""

	faces = []
	ofs = 0
	virtOfs = 0

	def readLeaf(marker:int):
		nonlocal ofs, virtOfs

		virtOfs += STACKLESS_LEAF_SIZE

		if marker == SHORT_LEAF_MARKER or marker == SHORT_LEAF_FLIP_MARKER:
			if ofs + 8 > len(data):
				raise ValueError(f"Short leaf overruns at {ofs}")

			w0, w1 = unpack_from("<II", data, ofs)
			ofs += 8

			w2 = QUAD_FLIPA_FLAG if marker == SHORT_LEAF_FLIP_MARKER else 0
			w3 = 0
		else:
			if ofs + 16 > len(data):
				raise ValueError(f"Leaf overruns at {ofs}")

			w0, w1, w2, w3 = unpack_from("<IIII", data, ofs)
			ofs += 16

		if not (w0 & QUAD_LEAF_FLAG):
			raise ValueError(f"Leaf at {ofs} is missing the quad leaf flag")

		if marker != RAW_LEAF_MARKER:
			faces.extend(_decodeLeafFaces(w0, w1, w2, w3, vertCount))

	def readNode(depth:int):
		nonlocal ofs, virtOfs

		if depth > MAX_TREE_DEPTH:
			raise ValueError("BVH tree is too deep")

		if ofs >= len(data):
			raise ValueError("Unexpected end of the wire tree")

		marker = data[ofs]
		ofs += 1

		if marker == 0 or marker == RAW_LEAF_MARKER or marker == SHORT_LEAF_MARKER or marker == SHORT_LEAF_FLIP_MARKER:
			readLeaf(marker)
		else:
			if marker > MAX_CHILD_COUNT:
				raise ValueError(f"Invalid internal node child count {marker}")

			virtOfs += STACKLESS_NODE_SIZE

			for _ in range(marker):
				readNode(depth + 1)

	while virtOfs < stacklessSize:
		if ofs >= len(data):
			break

		readNode(0)

	return faces


def decodeCollisionV3(block:bytes, swapAxes:bool = False):
	"""Decode a V3 collision resource.

	``block`` is the whole resource payload (magic included).  Returns a list of
	node dictionaries with ``name``, ``physMat``, ``verts`` (Dagor Y-up, ready for
	the DMF/OBJ writers) and ``faces`` (index triples).
	"""

	if not isV3(unpack_from("<I", block, 0)[0]):
		raise ValueError("Not a V3 collision resource")

	stream = decompressBlock(block[4:])

	if len(stream) < STREAM_HEADER_SIZE:
		raise ValueError("Collision stream is truncated")

	counts = unpack_from("<11I", stream, 64)
	nodeCount = counts[0]
	tmCount = counts[1]
	physMatCount = counts[6]
	capsuleCount = counts[7]
	convexCount = counts[8]
	namesSize = counts[9]
	matNamesSize = counts[10]

	bindOfs = STREAM_HEADER_SIZE
	nodeOfs = bindOfs + nodeCount * BIND_REC_SIZE
	tmOfs = nodeOfs + nodeCount * NODE_REC_SIZE
	blasOfs = tmOfs + (tmCount + counts[2] + counts[3]) * MATRIX_SIZE

	# counts[4] is the in-memory stackless tree size, the wire tree is smaller,
	# so the BLAS extent has to be derived from the sections that follow it
	# Capsule is Point3 a, float r, Point3 b: 28 persisted bytes, no SIMD padding.
	tailSize = physMatCount * 2 + capsuleCount * 28 + convexCount * 16 + namesSize + matNamesSize
	blasSize = len(stream) - blasOfs - tailSize

	if blasSize < 0:
		raise ValueError("Collision stream sizes do not add up")

	blas = stream[blasOfs:blasOfs + blasSize]

	capsuleOfs = blasOfs + blasSize + physMatCount * 2
	names = stream[capsuleOfs + capsuleCount * 28 + convexCount * 16:][:namesSize]

	def getName(ofs:int):
		if ofs >= len(names):
			return ""

		end = names.find(b"\x00", ofs)

		if end < 0:
			end = len(names)

		return names[ofs:end].decode("utf-8", "replace")

	# chunk boundaries: every BlasIoHeader magic is preceded by its 36 byte frame
	magic = b"dBLi"
	frameStarts = []
	search = 0

	while True:
		pos = blas.find(magic, search)

		if pos < 0:
			break

		if pos >= CHUNK_FRAME_SIZE:
			frameStarts.append(pos - CHUNK_FRAME_SIZE)

		search = pos + 1

	meshNodes = [i for i in range(nodeCount) if unpack_from("<I", stream, nodeOfs + i * NODE_REC_SIZE + 4)[0] > 0]

	if len(frameStarts) != len(meshNodes):
		raise Exception(f"Expected {len(meshNodes)} collision chunks, found {len(frameStarts)}")

	nodes = []

	for chunkId, nodeId in enumerate(meshNodes):
		recOfs = nodeOfs + nodeId * NODE_REC_SIZE
		nameOfs = unpack_from("<I", stream, recOfs)[0]
		idxCount = unpack_from("<I", stream, recOfs + 4)[0]
		physMatId = unpack_from("<h", stream, recOfs + 10)[0]

		frameOfs = frameStarts[chunkId]
		frameEnd = frameStarts[chunkId + 1] if chunkId + 1 < len(frameStarts) else len(blas)

		invScale = unpack_from("<3f", blas, frameOfs + 12)
		bMin = unpack_from("<3f", blas, frameOfs + 24)

		hdrOfs = frameOfs + CHUNK_FRAME_SIZE
		version = unpack_from("<H", blas, hdrOfs + 4)[0]
		treeBytes = unpack_from("<I", blas, hdrOfs + 8)[0]
		vertCount = unpack_from("<I", blas, hdrOfs + 12)[0]

		hdrSize = BLAS_IO_HEADER_SIZE + (4 if version >= 2 else 0)
		vertsOfs = hdrOfs + hdrSize
		treeOfs = vertsOfs + vertCount * 8

		verts = []

		for vertexId in range(vertCount):
			qx, qy, qz = _unpackVert21(blas, vertsOfs + vertexId * 8)
			verts.append((
				qx * invScale[0] + bMin[0],
				qy * invScale[1] + bMin[1],
				qz * invScale[2] + bMin[2]))

		tm = unpack_from("<12f", stream, tmOfs + nodeId * MATRIX_SIZE) if nodeId < tmCount else None

		if tm is not None:
			verts = [_transformVertex(tm, v) for v in verts]

		# Node transforms already carry the Dagor Y-up -> Z-up basis.  The DMF
		# reader/writer (and the Blender importer) expect plain Dagor Y-up, so the
		# extra legacy swap is opt-in only; applying it misaligns collision parts.
		if swapAxes:
			verts = [(v[0], v[2], v[1]) for v in verts]

		faces = _parseWireTree(blas[treeOfs:frameEnd], vertCount, treeBytes)

		expected = idxCount // 3

		if len(faces) != expected:
			raise Exception(f"Collision chunk '{getName(nameOfs)}' decoded {len(faces)} of {expected} faces")

		nodes.append({
			"name": getName(nameOfs),
			"physMat": None if physMatId < 0 else str(physMatId),
			"verts": tuple(verts),
			"faces": tuple(faces)})

	# Analytic primitives have no BLAS chunk. Tessellate them for OBJ/DMF.
	from parse.collision_primitives import box_mesh, capsule_mesh
	for nodeId in range(nodeCount):
		recOfs = nodeOfs + nodeId * NODE_REC_SIZE
		nodeType = stream[recOfs + 19]
		radius = unpack_from('<f', stream, recOfs + 44)[0]
		if nodeType not in (2, 3, 4) or radius < 0 or nodeId in meshNodes:
			continue
		bounds = unpack_from('<6f', stream, recOfs + 20)
		if nodeType == 2:
			verts, faces = box_mesh(bounds)
		elif nodeType == 3:
			center = tuple((bounds[i] + bounds[i + 3]) / 2 for i in range(3))
			verts, faces = capsule_mesh(center, center, radius)
		else:
			index = unpack_from('<H', stream, recOfs + 14)[0]
			if index >= capsuleCount:
				raise ValueError('Collision capsule index out of bounds')
			capsule = unpack_from('<7f', stream, capsuleOfs + index * 28)
			verts, faces = capsule_mesh(capsule[:3], capsule[4:], capsule[3])
		if nodeId < tmCount:
			tm = unpack_from('<12f', stream, tmOfs + nodeId * MATRIX_SIZE)
			verts = [_transformVertex(tm, v) for v in verts]
		if swapAxes:
			verts = [(v[0], v[2], v[1]) for v in verts]
		nameOfs = unpack_from('<I', stream, recOfs)[0]
		physMatId = unpack_from('<h', stream, recOfs + 10)[0]
		nodes.append(dict(name=getName(nameOfs), physMat=None if physMatId < 0 else str(physMatId),
			verts=tuple(verts), faces=tuple(faces)))
	return nodes
