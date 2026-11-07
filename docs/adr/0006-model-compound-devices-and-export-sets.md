# Model compound devices and export sets explicitly

PDK 命名把基础器件、隔离等级、拓扑和寄生结构编码在同一个 cell 或一组相关 cell 中，例如带 ISO 等级的 MOS。生成器将这些关系建模为组合器件，并允许用户建立持久的导出集，按器件、变体、规则类别和单条规则选择输出。

**Status**: accepted

**Consequences**: 导入器需要解析命名后缀、端口拓扑和关联 cell；选择组合器件时要自动提示或包含必要的依赖规则。项目文件必须保存选择集和依赖闭包，网页复制、`.scs`、JSON 等输出都从同一个导出集生成。
