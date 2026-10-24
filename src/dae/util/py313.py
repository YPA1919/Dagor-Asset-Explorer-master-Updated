"""Python 3.13 compatibility helpers.

CPython 3.13 removed chained ``@classmethod @property`` descriptors.  Such an
attribute now resolves to a bound classmethod object instead of the value the
property would return, which silently breaks anything using that value as a
key - the asset class registry in ``parse.realres`` for instance ends up keyed
by descriptor objects, so every resource is reported as an unknown class.

``fixAssetClasses`` replaces every chained descriptor in the asset class trees
with its computed value and rebuilds the class registry.
"""

def _materializeChainedDescriptors(cls: type) -> None:
	for name, raw in list(cls.__dict__.items()):
		if not isinstance(raw, classmethod):
			continue

		propDesc = raw.__func__

		if not isinstance(propDesc, property) or propDesc.fget is None:
			continue

		try:
			value = propDesc.fget(cls)
		except Exception:
			continue

		try:
			type.__setattr__(cls, name, value)
		except TypeError:
			# PyQt (sip) metaclasses reject attribute assignment from here.
			continue


def _walkClassTree(cls: type, seen: set) -> None:
	if cls in seen:
		return

	seen.add(cls)
	_materializeChainedDescriptors(cls)

	for subCls in cls.__subclasses__():
		_walkClassTree(subCls, seen)


def fixChainedDescriptors(*roots: type) -> int:
	seen:set[type] = set()

	for root in roots:
		_walkClassTree(root, seen)

	return len(seen)


def fixAssetClasses() -> None:
	from parse import realres
	from parse import material
	from parse import gameres

	roots = [realres.RealResData, material.DDSx, material.DDSxTexturePack2]

	packCls = getattr(gameres, "Pack", None)

	if isinstance(packCls, type):
		roots.append(packCls)

	# GUI actions carry the same chained descriptors (exportFormat,
	# exportMethodName, exportLODs ...).  Resolve them too, otherwise building
	# a context menu raises AttributeError on 3.13 and the tree shows
	# "Failed to compute preliminary data".
	try:
		from gui import customtreeview

		roots.append(customtreeview.CustomAction)
	except Exception:
		pass

	fixChainedDescriptors(*roots)

	# mutate in place: parse.gameres holds its own reference to this dict
	registry = {v.staticClassId : v for v in realres.REALRES_CLASSES_LIST}

	realres.REALRES_CLASSES_DICT.clear()
	realres.REALRES_CLASSES_DICT.update(registry)
