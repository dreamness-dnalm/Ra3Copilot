---
name: map-analyser
description: 分析 RA3 地图，提取出生点、油井、观测站、矿脉及推荐矿场位置。用户要求分析地图、查看地图资源分布时使用。
---

# Map Analyser

分析 RA3 地图中的关键点位与资源分布。

## 触发条件

当用户要求“分析地图”“查看地图资源分布”“出生点/油井/观测站/矿脉/矿场位置”“官方地图资源”等内容时，必须优先使用本 skill。

## 执行方式

调用工具 `analyse_ra3_map`，不要手写 C#，不要先查询类型信息，也不要自行请求底层 API。

工具参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `map_name` | 是 | 地图文件夹名或地图名，不需要 `.map` 后缀。例如 `官方地图_工业区_IndustrialStrength` |

工具内部会使用：

```
src/core/prompts/skills/map-analyser/references/analyser.cs
```

并通过 C# Runner 服务 `http://127.0.0.1:30033/api/csharpscript/run/code` 执行。

## 分析内容

工具会输出以下信息，坐标保留一位小数：

1. 玩家出生点位置：匹配 `Player_{n}_Start` 路径点
2. 油井位置：`OilDerrick` 单位
3. 观测站位置：`ObservationPostTechStructure` 单位
4. 矿脉及最佳矿场位置：`OreNode` 矿脉坐标，以及沿矿脉朝向偏移 180 单位的推荐矿场位置

## 响应处理

- 成功时，直接整理 `analyse_ra3_map` 的返回结果，用中文说明资源分布。
- 如果用户只要求分析，不要额外修改或保存地图。
- 失败时，说明当前没有完成分析，并给出工具返回的错误。常见原因：地图名错误、地图文件不存在、地编伴侣/C# Runner 未启动。

## 注意事项

- 仅传入地图名，无需完整路径。
- 若需扩展分析项，修改同目录下的 `references/analyser.cs`。
