# Use a local service for path access

浏览器的文件安全模型不允许静态 HTML 任意扫描用户输入的本机或远程路径，也不适合直接处理几十 GB 的 PDK 目录。采用一个只监听本机的 Python 小服务，让用户选择目录或输入路径；服务按需扫描候选文件并把结构化结果交给浏览器，远程来源通过现有 SSH 配置只读访问。

**Status**: accepted

**Consequences**: 第一版需要一个简单的启动命令和本地 HTTP/JSON 边界；服务必须按需读取文件、限制扫描根目录并记录来源，不把 PDK 内容上传到外部服务。
