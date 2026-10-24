import bpy
from os import path
from io import BufferedReader, BytesIO
from struct import unpack
from math import radians
from mathutils import Matrix, Vector
from .common import get_file_name, readInt, readString, deselect_all, set_mode_safe
from random import random

DMF_MAGIC = b"DMF\x02"
DMF_NO_PARENT = 0

MATRIX_TRANSLATE_ZERO = Matrix.Translation((0, 0, 0)).to_translation()
# Bone length, in file units.  Unchanged so bones keep their old size
# relative to the model now that the whole model is no longer x40.
MATRIX_TRANSLATE_ONE = Matrix.Translation((1 / 40, 0, 0)).to_translation()

OBJECT_SCALE = Vector((-1, 1, 1))
OBJECT_ROT = Vector((radians(90), radians(0), radians(90)))

TEXTURE_EXTENSION = ".dds"
TEXTURE_SLOT_COUNT = 11


def get_node_input(node, *names):
	"""Return the first input socket on *node* that exists.

	Blender 4.0 renamed several Principled BSDF sockets:
	"Specular" -> "Specular IOR Level", "Emission" -> "Emission Color".
	"""
	for name in names:
		if name in node.inputs:
			return node.inputs[name]

	raise KeyError(f"{node.bl_idname} has none of the inputs {names}")


def get_color_node_info():
	"""Describe this Build's split/combine colour nodes.

	Blender 4.0 replaced ShaderNodeSeparateRGB / ShaderNodeCombineRGB with
	ShaderNodeSeparateColor / ShaderNodeCombineColor, which use Color / Red /
	Green / Blue socket names instead of Image / R / G / B.
	"""
	if hasattr(bpy.types, "ShaderNodeSeparateColor"):
		return {
			"separate": "ShaderNodeSeparateColor",
			"combine": "ShaderNodeCombineColor",
			"separate_input": "Color",
			"channels": ("Red", "Green", "Blue"),
			"combine_output": "Color",
		}

	return {
		"separate": "ShaderNodeSeparateRGB",
		"combine": "ShaderNodeCombineRGB",
		"separate_input": "Image",
		"channels": ("R", "G", "B"),
		"combine_output": "Image",
	}

def get_tex_from_slots(tex_slots:list, id:int):
	if tex_slots[id] == "":
		return None
	else:
		return tex_slots[id]

def get_texture_dir(filepath:str):
	return path.join(path.dirname(filepath), "textures")

def get_texture_path(texture_dir:str, filename:str):
	return path.join(texture_dir, filename)

def get_texture(texture_dir:str, texture_name:str):
	if texture_name is None:
		texture_name = ""
	
	filename = texture_name.split("*")[0] + TEXTURE_EXTENSION
	
	image = bpy.data.images.get(filename)

	if image is None:
		texture_path = get_texture_path(texture_dir, filename)
		
		if path.exists(texture_path):
			image = bpy.data.images.load(texture_path)
	
	return image

class Skeleton:
	def __init__(self, skeleton_name:str):
		self.__bones_by_name:dict[str, tuple[bpy.types.Bone, Matrix]] = {}

		set_mode_safe("OBJECT")

		self.__armature = bpy.data.armatures.new(f"{skeleton_name}_Armature")
		self.__armature_obj = bpy.data.objects.new(f"{skeleton_name}_ArmatureObject", self.__armature)

		bpy.context.collection.objects.link(self.__armature_obj)
	
	def create_bones(self, f:BufferedReader):
		set_mode_safe("OBJECT")

		armature = self.__armature
		armature_obj = self.__armature_obj
		
		armature_obj.select_set(True)
		bpy.context.view_layer.objects.active = armature_obj

		bpy.ops.object.mode_set(mode = "EDIT")

		node_count = readInt(f)

		bones:list[bpy.types.Bone] = []
		parents:list[bpy.types.Bone] = []

		for idx in range(node_count):
			parent_idx = readInt(f) - 1
			name = readString(f)
			wtm = Matrix((
				unpack("4f", f.read(0x10)),
				unpack("4f", f.read(0x10)),
				unpack("4f", f.read(0x10)),
				unpack("4f", f.read(0x10))
			))

			
			bone = armature.edit_bones.new(name)
			bone.head = wtm @ MATRIX_TRANSLATE_ZERO
			bone.tail = wtm @ MATRIX_TRANSLATE_ONE

			bones.append(bone)
			parents.append(parent_idx)

			self.__bones_by_name[name] = (bone, wtm)
		
		for idx, parent_idx in enumerate(parents):
			if parent_idx != -1:
				bone = bones[idx]
				parent_bone = bones[parent_idx]

				bone.parent = parent_bone
		
		bpy.ops.object.mode_set(mode = "OBJECT")
	
	
	def getBone(self, name:str):
		if not self.hasBone(name):
			return None
		
		return self.__bones_by_name[name]

	def hasBone(self, name:str):
		return name in self.__bones_by_name

	@property
	def armature(self):
		return self.__armature
	
	@property
	def armature_obj(self):
		return self.__armature_obj

class DetailTexture:
	def __init__(self, idx:int, diffuse:str = None, normal:str = None):
		self.__idx = idx
		self.__diffuse = diffuse
		self.__normal = normal

	@property
	def diffuse(self):
		return self.__diffuse

	@property
	def idx(self):
		return self.__idx

	@property
	def normal(self):
		return self.__normal

	@property
	def is_none(self):
		return self.diffuse is None and self.normal is None

def load_skeleton(f:BufferedReader, ofs:int, name:str):
	if ofs != 0:
		f.seek(ofs, 0)

		skeleton = Skeleton(name)
		skeleton.create_bones(f)

		return skeleton
	else:
		return None

def set_skeleton_transform(skeleton:Skeleton):
	set_object_scale(skeleton.armature_obj)
	apply_object_transform(skeleton.armature_obj)

def get_scale(scale:str):
	if scale is None:
		return 1.0
	else:
		return 1 / float(scale)


def create_mapping_node(nodes:bpy.types.Nodes, 
			node_tree:bpy.types.NodeTree, 
			image_node:bpy.types.Node,
			scale_u:str = None,
			scale_v:str = None):
	
	scale_u = get_scale(scale_u)
	scale_v = get_scale(scale_v)

	texcoor_node = nodes.new("ShaderNodeTexCoord")
	mapping_node = nodes.new("ShaderNodeMapping")
	mapping_node.inputs["Scale"].default_value = Vector((scale_u, scale_v, 1.0))
	
	node_tree.links.new(texcoor_node.outputs["UV"], mapping_node.inputs["Vector"])
	node_tree.links.new(mapping_node.outputs["Vector"], image_node.inputs["Vector"])


# Approximate node heights for arrange_nodes().  Node.dimensions is only
# filled in while the node editor draws, so it cannot be queried here.
NODE_HEIGHTS = {
	"ShaderNodeBsdfPrincipled": 800,
	"ShaderNodeValToRGB": 350,
	"ShaderNodeTexImage": 380,
	"ShaderNodeTexCoord": 300,
	"ShaderNodeMapping": 220,
	"ShaderNodeNormalMap": 220,
	"ShaderNodeMixShader": 160,
	"ShaderNodeOutputMaterial": 170,
	"ShaderNodeMath": 190,
	"ShaderNodeInvert": 190,
	"ShaderNodeGamma": 170,
	"ShaderNodeSeparateColor": 140,
	"ShaderNodeCombineColor": 140,
	"ShaderNodeSeparateRGB": 140,
	"ShaderNodeCombineRGB": 140,
}


def get_node_height(node):
	if node.bl_idname == "ShaderNodeTexImage" and node.image is None:
		return 220

	height = NODE_HEIGHTS.get(node.bl_idname)

	if height is None:
		height = 40 + 22 * max(len(node.inputs), len(node.outputs))

	return height


def arrange_nodes(node_tree, spacing_x:float = 170.0, spacing_y:float = 60.0):
	"""Lay a node tree out from left to right.

	Nodes are grouped into columns by dependency depth. Each node is then pulled
	towards the vertical centre of the nodes it is connected to while the column
	keeps its members apart, so the links stay short and mostly diagonal.
	"""
	if len(node_tree.nodes) < 2:
		return

	depths = {}

	def get_depth(node, seen = None):
		if node.name in depths:
			return depths[node.name]

		seen = set() if seen is None else seen

		if node.name in seen:
			return 0

		seen.add(node.name)

		depth = 0

		for socket in node.inputs:
			for link in socket.links:
				depth = max(depth, get_depth(link.from_node, seen) + 1)

		seen.discard(node.name)

		depths[node.name] = depth

		return depth

	columns = {}

	for node in node_tree.nodes:
		columns.setdefault(get_depth(node), []).append(node)

	centers = {node.name: 0.0 for node in node_tree.nodes}

	# Pull every node to the vertical centre of the nodes it is connected to,
	# then push overlapping nodes apart inside their column. Alternating the
	# sweep direction on every pass lets the positions settle instead of
	# drifting in one direction.
	for iteration in range(12):
		for depth in sorted(columns, reverse=bool(iteration % 2)):
			requests = []

			for node in columns[depth]:
				neighbours = [centers[link.from_node.name]
					for socket in node.inputs
					for link in socket.links
					if link.from_node.name in centers]

				neighbours += [centers[link.to_node.name]
					for socket in node.outputs
					for link in socket.links
					if link.to_node.name in centers]

				if neighbours:
					centre = sum(neighbours) / len(neighbours)
				else:
					centre = centers[node.name]

				requests.append((centre, node))

			# Larger Y is higher on screen, so the topmost node is placed first.
			requests.sort(key=lambda entry: -entry[0])

			tops = []
			cursor = None

			for centre, node in requests:
				height = get_node_height(node)
				top = centre + height / 2

				if cursor is not None:
					top = min(top, cursor)

				tops.append(top)
				cursor = top - height - spacing_y

			# Re-centre the column on what it asked for so it does not drift.
			wanted = sum(centre + get_node_height(node) / 2
				for centre, node in requests) / len(requests)
			shift = wanted - sum(tops) / len(tops)

			for (centre, node), top in zip(requests, tops):
				top += shift

				node.location.y = top
				centers[node.name] = top - get_node_height(node) / 2

	x = 0.0

	for depth in sorted(columns):
		column_width = max(node.width for node in columns[depth])

		for node in columns[depth]:
			node.location.x = x

		x += column_width + spacing_x


def create_normal_node(nodes, node_tree, principled_bsdf):
	normal_node = nodes.new("ShaderNodeTexImage")

	color_node = nodes.new("ShaderNodeValToRGB")
	color_node.color_ramp.elements[0].color = (1.0, 1.0, 1.0, 1.0)
	color_node.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)

	# Blender 4.0 renamed the split/combine colour nodes; pick the pair this
	# build actually provides and use its socket names.
	color_info = get_color_node_info()
	separate_rgb_node = nodes.new(color_info["separate"])
	combine_rgb_node = nodes.new(color_info["combine"])
	red_channel, green_channel, blue_channel = color_info["channels"]

	node_tree.links.new(normal_node.outputs["Color"], separate_rgb_node.inputs[color_info["separate_input"]])
	node_tree.links.new(separate_rgb_node.outputs[blue_channel], get_node_input(principled_bsdf, "Metallic"))

	node_tree.links.new(normal_node.outputs["Alpha"], combine_rgb_node.inputs[red_channel])
	node_tree.links.new(separate_rgb_node.outputs[green_channel], combine_rgb_node.inputs[green_channel])
	node_tree.links.new(color_node.outputs["Color"], combine_rgb_node.inputs[blue_channel])

	normalmap_node = nodes.new("ShaderNodeNormalMap")
	node_tree.links.new(combine_rgb_node.outputs[color_info["combine_output"]], normalmap_node.inputs["Color"])
	node_tree.links.new(normalmap_node.outputs["Normal"], get_node_input(principled_bsdf, "Normal"))

	invert_node = nodes.new("ShaderNodeInvert")
	node_tree.links.new(normal_node.outputs["Alpha"], invert_node.inputs["Color"])
	node_tree.links.new(invert_node.outputs["Color"], get_node_input(principled_bsdf, "Specular IOR Level", "Specular"))

	return normal_node, separate_rgb_node


def create_materials(f:BufferedReader, 
			 texture_dir:str, 
			 random_viewport_color:bool, 
			 recreate_materials:bool,
			 import_textures:bool):
	material_count = readInt(f)
	
	for _ in range(material_count):
		material_name = readString(f)
		shader_class = readString(f)

		diff = unpack("ffff", f.read(0x10))
		amb = unpack("ffff", f.read(0x10))
		emis = unpack("ffff", f.read(0x10))
		spec = unpack("ffff", f.read(0x10))

		tex_slots = [readString(f) for _ in range(TEXTURE_SLOT_COUNT)]

		params = {}
		param_count = readInt(f)

		for _ in range(param_count):
			param_key = readString(f)
			param_value = readString(f)

			params[param_key] = param_value
		
		# print(f"{material_name}:{shader_class}")
		# for k, v in enumerate(tex_slots):
		# 	print(f"\t{k}={v}")
		# print(f"\tparams={params}")

		if bpy.data.materials.get(material_name) is not None and not recreate_materials:
			continue
		
		detail:list[DetailTexture] = []

		diffuse = get_tex_from_slots(tex_slots, 0)
		normal = get_tex_from_slots(tex_slots, 2)

		ao = None
		alpha = None
		mask = None

		diffuse_is_detail1 = False

		if shader_class == "rendinst_tree_colored":
			alpha = get_tex_from_slots(tex_slots, 1)
		elif shader_class == "rendinst_simple_layered":
			detail_diffuse = get_tex_from_slots(tex_slots, 1)
			detail_normal = get_tex_from_slots(tex_slots, 3)

			detail_tex = DetailTexture(detail_diffuse, detail_normal)
			
			detail.append(detail_tex)
		else:
			layered = shader_class.find("layered") != -1
			dynamic = shader_class.find("dynamic") != -1

			mask = get_tex_from_slots(tex_slots, 1)

			if not dynamic or layered:
				detailStart = 3
			else:
				ao = get_tex_from_slots(tex_slots, 3)
				detailStart = 4
			
			if shader_class != "dynamic_painted_by_mask":
				for i in range(detailStart, TEXTURE_SLOT_COUNT, 2):
					detail_diffuse = get_tex_from_slots(tex_slots, i)

					if detail_diffuse is None:
						continue

					detail_normal = get_tex_from_slots(tex_slots, i + 1)

					detail_tex = DetailTexture(i, detail_diffuse, detail_normal)
					detail.append(detail_tex)
			
				if layered and len(detail) >= 1:
					diffuse = detail[0].diffuse
					normal = detail[0].normal if detail[0].normal is not None else ""
					detail = detail[1:]

					diffuse_is_detail1 = True


		material = bpy.data.materials.new(name=material_name)

		if random_viewport_color:
			material.diffuse_color = (random(), random(), random(), 1)

		
		material.use_nodes = True
		# material.use_backface_culling = two_sided

		node_tree = material.node_tree
		nodes = node_tree.nodes

		nodes.clear()

		material_output = nodes.new("ShaderNodeOutputMaterial")
		principled_bsdf = nodes.new("ShaderNodeBsdfPrincipled")
		principled_bsdf.inputs["Base Color"].default_value = diff
		# principled_bsdf.inputs["Emission"].default_value = emis # some textures appear completely white with this
		principled_bsdf.inputs["Roughness"].default_value = 1.0

		diffuse_texture = get_texture(texture_dir, diffuse) if import_textures else None
		
		diffuse_node = nodes.new("ShaderNodeTexImage")
		if diffuse_texture is not None:
			diffuse_node.image = diffuse_texture

		if diffuse_is_detail1:
			create_mapping_node(nodes,
			   node_tree,
			   diffuse_node,
			   params.get("detail1_tile_u"),
			   params.get("detail1_tile_v"))
		

		if diffuse_node.image is not None:
			node_tree.links.new(diffuse_node.outputs["Color"], principled_bsdf.inputs["Base Color"])
		
		normal_texture = get_texture(texture_dir, normal) if import_textures else None

		camo_node = None
		hasMask = mask is not None
		
		if hasMask:
			camo_node = nodes.new("ShaderNodeTexImage")
			create_mapping_node(nodes, 
			   node_tree, 
			   camo_node, 
			   params.get("mask_tile_u"),
			   params.get("mask_tile_v"))
			camo_texture = get_texture(texture_dir, mask) if import_textures else None
			
			if camo_texture is not None:
				camo_node.image = camo_texture
		
		alpha_node = None

		if alpha is not None:
			alpha_node = nodes.new("ShaderNodeTexImage")
			alpha_texture = get_texture(texture_dir, alpha) if import_textures else None
			
			if alpha_texture is not None:
				alpha_node.image = alpha_texture
		
		# if normal_texture is not None:
		normal_node, separate_rgb_node = create_normal_node(nodes, node_tree, principled_bsdf)
		
		if normal_texture is not None:
			normal_node.image = normal_texture
		
		if diffuse_is_detail1:
			create_mapping_node(nodes,
			   node_tree,
			   normal_node,
			   params.get("detail1_tile_u"),
			   params.get("detail1_tile_v"))

		if hasMask:
			invert_node = nodes.new("ShaderNodeInvert")
			node_tree.links.new(separate_rgb_node.outputs[get_color_node_info()["channels"][2]], invert_node.inputs["Color"])

			div_node = nodes.new("ShaderNodeMath")
			div_node.operation = "DIVIDE"
			
			node_tree.links.new(invert_node.outputs["Color"], div_node.inputs[0])
			div_node.inputs[1].default_value = 2.0

			mult_node = nodes.new("ShaderNodeMath")
			mult_node.operation = "MULTIPLY"
			node_tree.links.new(div_node.outputs["Value"], mult_node.inputs[0])

			if alpha_node is None:
				node_tree.links.new(diffuse_node.outputs["Alpha"], mult_node.inputs[1])
			else:
				node_tree.links.new(alpha_node.outputs["Alpha"], mult_node.inputs[1])

			invert2_node = nodes.new("ShaderNodeInvert")

			gamma = None

			if params.get("mask_gamma_end") is not None:
				gamma = params.get("mask_gamma_end")
			elif params.get("mask_gamma_start") is not None:
				gamma = params.get("mask_gamma_start")
			

			if gamma is not None:
				gamma_node = nodes.new("ShaderNodeGamma")
				gamma_node.inputs["Gamma"].default_value = float(gamma) * 2

				out_node = gamma_node.outputs["Color"]
				node_tree.links.new(mult_node.outputs["Value"], gamma_node.inputs["Color"])
			else:
				out_node = mult_node.outputs["Value"]

			node_tree.links.new(out_node, invert2_node.inputs["Color"])
		# elif masked:
		# 	invert2_node = nodes.new("ShaderNodeInvert")
		# 	node_tree.links.new(diffuse_node.outputs["Alpha"], invert_node.inputs["Color"])

		if hasMask:
			mix_node = nodes.new("ShaderNodeMixShader")
			node_tree.links.new(invert2_node.outputs["Color"], mix_node.inputs["Fac"])
			node_tree.links.new(camo_node.outputs["Color"], mix_node.inputs[1])
			node_tree.links.new(principled_bsdf.outputs["BSDF"], mix_node.inputs[2])

			output_shader = mix_node.outputs["Shader"]
			node_tree.links.new(mix_node.outputs["Shader"], material_output.inputs["Surface"])
		else:
			mix_node = None

			# Only drive Alpha when the texture it comes from actually exists;
			# an empty image node would output alpha 0 (invisible material).
			if alpha_node is None:
				alpha_source = diffuse_node if diffuse_node.image is not None else None
			else:
				alpha_source = alpha_node if alpha_node.image is not None else None
			
			if alpha_source is not None:
				alpha_output = alpha_source.outputs["Alpha"]
				
				if shader_class.find("masked") != -1:
					invert_alpha_node = nodes.new("ShaderNodeInvert")
					node_tree.links.new(alpha_output, invert_alpha_node.inputs["Color"])
					alpha_output = invert_alpha_node.outputs["Color"]
				
				node_tree.links.new(alpha_output, principled_bsdf.inputs["Alpha"])
			
			output_shader = principled_bsdf.outputs["BSDF"]
		
		# detail_mix_node = None

		for detail_tex in detail:
			detail_diffuse_node = nodes.new("ShaderNodeTexImage")
			detail_diffuse = get_texture(texture_dir, detail_tex.diffuse) if import_textures else None
			
			create_mapping_node(nodes, 
			   node_tree, 
			   detail_diffuse_node, 
			   params.get(f"detail{detail_tex.idx}_tile_u"),
			   params.get(f"detail{detail_tex.idx}_tile_v"))
			
			if detail_diffuse is not None:
				detail_diffuse_node.image = detail_diffuse
			
			if detail_tex.normal is not None:
				detail_bsdf = nodes.new("ShaderNodeBsdfPrincipled")
				detail_bsdf.inputs["Base Color"].default_value = diff
				get_node_input(detail_bsdf, "Emission Color", "Emission").default_value = emis
				detail_bsdf.inputs["Roughness"].default_value = 1.0

				detail_normal_node, detail_separate_rgb_node = create_normal_node(nodes, node_tree, detail_bsdf)
				detail_normal = get_texture(texture_dir, detail_tex.normal) if import_textures else None
				
				if detail_normal is not None:
					detail_normal_node.image = detail_normal

				create_mapping_node(nodes, 
					node_tree, 
					detail_normal_node, 
					params.get(f"detail{detail_tex.idx}_tile_u"),
					params.get(f"detail{detail_tex.idx}_tile_v"))
				
				node_tree.links.new(detail_diffuse_node.outputs["Color"], detail_bsdf.inputs["Base Color"])
				shader_out = detail_bsdf.outputs["BSDF"]
			else:
				shader_out = detail_diffuse_node.outputs["Color"]
			

			detail_mix_node = nodes.new("ShaderNodeMixShader")
			
			node_tree.links.new(shader_out, detail_mix_node.inputs[1])
			node_tree.links.new(output_shader, detail_mix_node.inputs[2])

			output_shader = detail_mix_node.outputs["Shader"]

		node_tree.links.new(output_shader, material_output.inputs["Surface"])
		

		if shader_class.find("atest") != -1:
			# EEVEE Next (Blender 4.2+) replaced blend_method with
			# surface_render_method; set whichever one this Blender has.
			try:
				material.blend_method = "CLIP"
			except (AttributeError, TypeError):
				pass

			if hasattr(material, "surface_render_method"):
				material.surface_render_method = "DITHERED"

		arrange_nodes(material.node_tree)


def load_materials(f:BufferedReader, 
		   ofs:int, 
		   texture_dir:str, 
		   random_viewport_color:bool, 
		   recreate_materials:bool,
		   import_textures:bool):
	if ofs != 0:
		f.seek(ofs, 0)

		create_materials(f, 
		   texture_dir, 
		   random_viewport_color, 
		   recreate_materials,
		   import_textures)



class VertexRemapper:
	def __init__(self, verts:tuple, uvs:tuple, normals:tuple):
		self.vert_remap:dict[int, int] = {}
		self.verts = []
		self.uvs = []
		self.normals = []
		self.__vert_idx = 0

		self.__verts = verts
		self.__uvs = uvs
		self.__normals = normals
	
	def get_remapped_idx(self, idx:int):
		if not idx in self.vert_remap:
			self.vert_remap[idx] = self.__vert_idx

			self.verts.append(self.__verts[idx])
			self.normals.append(self.__normals[idx])
			self.uvs.append(self.__uvs[idx])

			self.__vert_idx += 1
		
		return self.vert_remap[idx]
	
	def get_remapped_face(self, face:tuple):
		return (self.get_remapped_idx(face[0]), 
	  			self.get_remapped_idx(face[1]), 
				self.get_remapped_idx(face[2]))
	
	def remap_object(self, faces:tuple):
		return tuple(self.get_remapped_face(face) for face in faces), self.verts, self.uvs, self.normals


def create_mesh(f:BufferedReader, name:str, global_verts:tuple, global_uvs:tuple, global_normals:tuple):
	face_count = readInt(f)
	faces = tuple(unpack("III", f.read(0xC)) for _ in range(face_count))

	remapper = VertexRemapper(global_verts, global_uvs, global_normals)
	
	obj_faces, obj_verts, obj_uvs, obj_normals = remapper.remap_object(faces)

	mesh = bpy.data.meshes.new(name)

	if bpy.app.version >= (3, 6):
		mesh.from_pydata(obj_verts, [], obj_faces, False)
	else:
		mesh.from_pydata(obj_verts, [], obj_faces)
	
	uv_layer = mesh.uv_layers.new().data
	for loop in mesh.loops:
		uv_layer[loop.index].uv = obj_uvs[loop.vertex_index]
	
	mesh.normals_split_custom_set_from_vertices(obj_normals)
	
	if hasattr(mesh, "use_auto_smooth"):
		mesh.use_auto_smooth = True
	# mesh.use_auto_smooth = True

	return mesh

def assign_mesh_materials(f:BufferedReader, mesh:bpy.types.Mesh):
	mat_count = readInt(f)
	
	prev_idx = 0
	prev_mat = None

	for i in range(mat_count):
		start_idx = readInt(f)
		mat_name = readString(f)

		material = bpy.data.materials.get(mat_name)

		if material is None:
			material = bpy.data.materials.new(mat_name)
		
		mesh.materials.append(material)

		assign_material(mesh, prev_mat, prev_idx, start_idx)

		prev_idx = start_idx
		prev_mat = i
	
	assign_material(mesh, prev_mat, prev_idx, len(mesh.polygons))

def assign_material(mesh:bpy.types.Mesh, material:bpy.types.Material, start_idx:int, end_idx:int):
	if material is not None:
		for k in range(start_idx, end_idx):
			mesh.polygons[k].material_index = material

def create_object(f:BufferedReader, global_verts:tuple, global_uvs:tuple, global_normals:tuple):
	obj_name = readString(f)
	skinned = readInt(f) == 1
	
	mesh = create_mesh(f, obj_name, global_verts, global_uvs, global_normals)
	assign_mesh_materials(f, mesh)
	
	mesh.validate()
	mesh.update()
	
	ob = bpy.data.objects.new(obj_name, mesh)
	
	return ob, skinned

def apply_object_transform(ob:bpy.types.Object):
	set_mode_safe("OBJECT")
	
	deselect_all()

	bpy.context.view_layer.objects.active = ob
	ob.select_set(True)

	bpy.ops.object.transform_apply(scale=True)

	deselect_all()

def set_object_scale(ob:bpy.types.Object):
	ob.scale = OBJECT_SCALE
	ob.rotation_euler = OBJECT_ROT

def set_bone_parent(ob, armature_obj, armature, bone_name, relative_parenting):
	set_mode_safe("OBJECT")
	
	deselect_all()

	bpy.context.view_layer.objects.active = armature_obj
	armature_obj.select_set(True)
	
	bpy.ops.object.mode_set(mode = "EDIT")

	# A DMF does not always carry the skeleton we expect: the export can ship an
	# armature without any bone, or name its bones differently from the mesh
	# objects.  Fall back to the first bone, and to a plain object parent when
	# there is none, instead of raising KeyError.
	edit_bones = armature.edit_bones

	if bone_name not in edit_bones:
		bone_name = edit_bones[0].name if len(edit_bones) > 0 else None

	if bone_name is not None:
		edit_bones.active = edit_bones[bone_name]
	
	bpy.ops.object.mode_set(mode = "OBJECT")

	deselect_all()
	bpy.context.view_layer.objects.active = armature_obj
	
	if bone_name is None:
		ob.select_set(True)
		armature_obj.select_set(True)
		bpy.ops.object.parent_set(type = "OBJECT", keep_transform=True)

		return

	ob.select_set(True)
	armature_obj.select_set(True)
	
	if relative_parenting:
		parent_type = "BONE_RELATIVE"
	else:
		parent_type = "BONE"
	
	bpy.ops.object.parent_set(type = parent_type, keep_transform=True)

def set_object_transform(ob:bpy.types.Object, skeleton:Skeleton, apply_scale:bool, skinned:bool, relative_parenting:bool):
	obj_name = ob.name

	if skeleton is not None:
		armature_obj = skeleton.armature_obj
		armature = skeleton.armature

		if skeleton.hasBone(obj_name):
			if not skinned:
				bone, wtm = skeleton.getBone(obj_name)
				
				ob.matrix_world = wtm
				apply_object_transform(ob)

			if apply_scale:
				set_object_scale(ob)
				apply_object_transform(ob)
			
			set_bone_parent(ob, armature_obj, armature, obj_name, relative_parenting)
		else:
			if apply_scale:
				set_object_scale(ob)
				apply_object_transform(ob)
			
			set_bone_parent(ob, armature_obj, armature, "Bone", relative_parenting)
	elif apply_scale:
		set_object_scale(ob)
		apply_object_transform(ob)



def load(filepath:str, 
	 apply_scale:bool = True, 
	 random_viewport_color = True, 
	 recreate_materials = False, 
	 import_textures = True,
	 relative_parenting = True,
	 update_viewlayer = True):
	model_name = get_file_name(filepath)
	texture_dir = get_texture_dir(filepath)

	view_layer = bpy.context.view_layer
	collection = view_layer.active_layer_collection.collection
	
	with open(filepath, "rb") as file:
		if file.read(4) != DMF_MAGIC:
			raise Exception("Invalid magic, unsupported DMF version? Update your tools, export the model and try again.")
		else:
			file.seek(0, 0)
		
		f = BytesIO(file.read())
		f.seek(4, 1)
		
		data_ofs, mat_ofs, ske_ofs = unpack("III", f.read(0xC))

		load_materials(f, 
		 mat_ofs, 
		 texture_dir, 
		 random_viewport_color, 
		 recreate_materials,
		 import_textures)

		skeleton = load_skeleton(f, ske_ofs, model_name)

		# main part
		
		f.seek(data_ofs, 0)

		vert_scale = unpack("fff", f.read(0xC)) # unused, scale is already applied

		vert_count = readInt(f)

		verts = tuple(unpack("fff", f.read(0xC)) for _ in range(vert_count))
		normals = tuple(unpack("fff", f.read(0xC)) for _ in range(vert_count))
		uvs = tuple(unpack("ff", f.read(0x8)) for _ in range(vert_count))
		
		obj_count = readInt(f)

		if skeleton is None and obj_count > 1:
			skeleton = Skeleton(model_name) # create an empty skeleton to append our dynmodel's objects to
			# if we are a rendinst then do not make a skeleton
			
			set_mode_safe("OBJECT")
			deselect_all()

			skeleton.armature_obj.select_set(True)
			bpy.context.view_layer.objects.active = skeleton.armature_obj

			bpy.ops.object.mode_set(mode = "EDIT")
			
			bone = skeleton.armature.edit_bones.new("Bone")
			bone.head = MATRIX_TRANSLATE_ZERO
			bone.tail = MATRIX_TRANSLATE_ONE

			bpy.ops.object.mode_set(mode = "OBJECT")
		
		if skeleton is not None and apply_scale:
			set_skeleton_transform(skeleton)
		
		all_objects = [None] * obj_count
		
		for i in range(obj_count):
			ob, skinned = create_object(f, verts, uvs, normals)
			
			all_objects[i] = ob
			
			collection.objects.link(ob)
			
			set_object_transform(ob, skeleton, apply_scale, skinned, relative_parenting)
		
		set_mode_safe("OBJECT")
		deselect_all()
		
		for ob in all_objects:
			ob.select_set(True)
		

	if update_viewlayer:
		view_layer.update()


	return {"FINISHED"}