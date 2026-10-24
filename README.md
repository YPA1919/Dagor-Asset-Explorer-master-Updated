# Dagor Asset Explorer Updated

This is a Dagor Asset Explorer build with most known issues fixed. It reads War Thunder Dagor resource packages and exports models, collision geometry, and textures. The bundled Blender plug-in supports Blender 2.92 through Blender 5.3.  Repaired and updated by Deepseek and ChatGPT.

Original tool and plug-in repositories:

- https://github.com/quentin-dh/Dagor-Asset-Explorer
- https://github.com/quentin-dh/Dagor-Asset-Explorer-Tools

## Usage

Double-click `DagorAssetExplorer.exe` in this directory to start the graphical interface. On the first run, load resources in this order:

1. Open the War Thunder game root from the `File` menu. This is usually a path ending in `.../War Thunder`.
2. Load the matching resource description file. Models usually require `riDesc.bin` or `dynModelDesc.bin`, commonly found under `content/base/res` or the relevant DLC directory.
3. Open the `.grp` file that contains the resource you want.
4. Open the corresponding `.dxp.bin` texture pack if you also want to export textures.
5. Find the model in the resource tree and right-click it to choose an export format.

The program writes exported files to the output directory you select. Models normally produce OBJ, MTL, and DMF files. When texture export is enabled, textures are written to a `textures` subdirectory inside the output directory. DMF preserves skeletons, material groups, and LOD information, so DMF is recommended for models with bones.

## Supported Resources

- `RendInst`: static models and LODs;
- `DynModel`: dynamic models, skeletal models, and skinned models;
- `GeomNodeTree`: skeleton trees;
- `CollisionGeom`: collision models;
- `DDSx` / `DXP`: Dagor textures and texture packs;
- selected scene resources, prop layouts, and other Dagor resource types.

## Blender Import

The `io_scene_date_updated` directory contains the Blender plug-in for DMF and DPL files. To install it:

1. Open Blender and go to `Edit > Preferences > Add-ons`.
2. Click `Install...` and select `io_scene_date_updated.zip` from this directory.
3. Enable `Dagor Asset Explorer Tools`.
4. Use `File > Import > Import DMF` to import a model, or use the corresponding DPL import entry for prop layouts.

## Textures and Special Resources

Some game textures are differential textures that must be combined with a paired base texture at runtime. When exported alone, they cannot be previewed as complete images. A small number of legacy floating-point DDS and legacy luminance formats may not be decoded by third-party viewers such as Pillow, although the DDS data itself can still be written.

The game packages also contain a small number of truncated resources and legacy vegetation or shader-mesh layouts. Guessing the layout of these resources can produce misaligned geometry, so the program preserves the error and records it in the log.

## Directory Layout

```text
Dagor-Asset-Explorer-master-Updated/
├─ DagorAssetExplorer.exe
├─ _internal/          PyInstaller runtime dependencies
├─ lib/                native decoding libraries
├─ patterns/           resource recognition rules
├─ res/                icons and interface resources
├─ src/                Python source code
├─ ui/                 interface files
├─ io_scene_date_updated/
├─ io_scene_date_updated.zip
├─ settings.json
└─ DagorAssetExplorer.log
```

## Original Credits

- Quentin H.
- CloakerSmoker
