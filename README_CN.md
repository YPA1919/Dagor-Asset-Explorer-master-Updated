# Dagor Asset Explorer 修复版

这是一个修复了大部分已知问题的 Dagor Asset Explorer 构建版本。它可以读取《War Thunder》的 Dagor 资源包，并导出模型、碰撞几何体和贴图。随附的 Blender 插件支持 Blender 2.92 至 Blender 5.3。由 Deepseek 和 ChatGPT 修复与更新。

原始工具和插件仓库：

- https://github.com/quentin-dh/Dagor-Asset-Explorer
- https://github.com/quentin-dh/Dagor-Asset-Explorer-Tools

## 使用方法

双击本目录中的 `DagorAssetExplorer.exe` 启动图形界面。首次运行时，建议按以下顺序加载资源：

1. 在 `File` 菜单中打开 War Thunder 游戏根目录，通常是以 `.../War Thunder` 结尾的路径。
2. 加载匹配的资源描述文件。模型通常需要 `riDesc.bin` 或 `dynModelDesc.bin`，这些文件一般位于 `content/base/res` 或相应的 DLC 目录下。
3. 打开包含目标资源的 `.grp` 文件。
4. 如果还需要导出贴图，请打开对应的 `.dxp.bin` 纹理包。
5. 在资源树中找到模型，右键选择导出格式。

程序会将导出的文件写入你选择的输出目录。模型通常会生成 OBJ、MTL 和 DMF 文件。启用贴图导出后，贴图会写入输出目录中的 `textures` 子目录。DMF 可以保留骨骼、材质组和 LOD 信息，因此带骨骼的模型建议使用 DMF 格式。

## 支持的资源

- `RendInst`：静态模型和 LOD；
- `DynModel`：动态模型、骨骼模型和蒙皮模型；
- `GeomNodeTree`：骨骼树；
- `CollisionGeom`：碰撞模型；
- `DDSx` / `DXP`：Dagor 贴图和纹理包；
- 部分场景资源、道具布局以及其他 Dagor 资源类型。

## Blender 导入

`io_scene_date_updated` 目录包含用于导入 DMF 和 DPL 文件的 Blender 插件。安装方法如下：

1. 打开 Blender，进入 `Edit > Preferences > Add-ons`。
2. 点击 `Install...`，选择本目录中的 `io_scene_date_updated.zip`。
3. 启用 `Dagor Asset Explorer Tools`。
4. 使用 `File > Import > Import DMF` 导入模型，或使用对应的 DPL 导入项导入道具布局。

## 贴图和特殊资源

部分游戏贴图是差分纹理，必须在运行时与配对的基础贴图合并。单独导出时，这些贴图无法作为完整图像预览。少量旧式浮点 DDS 和旧式 luminance 格式可能无法被 Pillow 等第三方查看器解码，但 DDS 数据本身仍然可以写出。

游戏资源包中还包含少量截断资源，以及旧式植被或 shader mesh 布局。强行猜测这些资源的布局可能导致几何体错位，因此程序会保留错误，并将错误记录到日志中。

## 目录结构

```text
Dagor-Asset-Explorer-master-Updated/
├─ DagorAssetExplorer.exe
├─ _internal/          PyInstaller 运行时依赖
├─ lib/                原生解码库
├─ patterns/           资源识别规则
├─ res/                图标和界面资源
├─ src/                Python 源代码
├─ ui/                 界面文件
├─ io_scene_date_updated/
├─ io_scene_date_updated.zip
├─ settings.json
└─ DagorAssetExplorer.log
```

## 原始项目致谢

- Quentin H.
- CloakerSmoker
