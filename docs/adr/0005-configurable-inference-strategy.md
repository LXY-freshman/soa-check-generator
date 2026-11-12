# Use a configurable inference strategy

Process inputs may contain device-family levels, absolute terminal limits, topology differences, conditional SOA curves, and model parameters. Numbers in a device name are only candidate clues; explicit limits take priority, and a configurable safety margin may fill a candidate only when stronger evidence is absent. The strategy covers MOS, LDMOS, DEMOS, diode, BJT, resistor, and capacitor families while preserving the evidence chain in the derived configuration.

**Status**: accepted

**Consequences**: 推断器不能只按器件名称正则表达式生成规则；它需要器件特征、端口拓扑、极性和规则类别的结构化字段。用户可以修改裕量和结果，且每条推断规则都必须显示来源和计算过程。
