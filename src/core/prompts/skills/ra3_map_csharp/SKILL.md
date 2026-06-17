---
name: ra3-map-csharp
description: 编写c#程序, 创建/编辑ra3地图文件.
---

# RA3 Map CSharp

## RA3 地图中的术语与概念

### 地图的尺寸与坐标
地图有两种坐标系
#### 网格坐标
网格坐标为大于0的整数  
将地图分割为多个正方形区域, 原点为左下角的区域, 水平向右的方向为x轴, 垂直向上的方向为y轴  
网格坐标用于描述`地图尺寸`, `地形高度`, `地图纹理`信息  
地图宽度 = 可游玩区域宽度 + 地图边界宽度 * 2  
地图高度 = 可游玩区域高度 + 地图边界宽度 * 2  

#### 实际坐标  
实际坐标为浮点数  
精准地描述地图中的位置, `网格坐标`中的一个单位长度为`实际坐标`中的10个单位长度  
主要用于表示`物体`或`路径点`的位置  

cell_x = ceil((real_x - boder_width * 10) / 10)  
cell_y = ceil((real_y - board_width * 10) / 10)  

## 编程指导

### 引入依赖
```
using Dreamness.Ra3.Map.Facade.Core;
using Dreamness.Ra3.Map.Facade.Util;
```

### 新建/打开/保存 地图文件
```csharp
// 新建一张新地图, 可游玩区域为100x200, 地图边界宽度为10
var ra3Map1 = Ra3MapFacade.NewMap(100, 200, 10);

// 从默认地图文件夹中加载一张已有地图
var ra3Map2 = Ra3MapFacade.Open(Ra3PathUtil.RA3MapFolder, "map_name");

// 另存为; 如果是新地图, 保存时必须用SaveAs, 而不是Save
ra3Map1.SaveAs(Ra3PathUtil.RA3MapFolder, "target_map_name");

// 保存
ra3Map2.Save();
```

### 获取地图信息
```csharp
int mapHeight = ra3Map.MapHeight;
int mapWidth = ra3Map.MapWidth;
var mapBorderWidth = ra3Map.MapBorderWidth;
var mapPlayableHeight = ra3Map.MapPlayableHeight;
var mapPlayableWidth = ra3Map.MapPlayableWidth;
```

### 高度数据  
```csharp
// 获取坐标处的高度
float height = ra3Map.GetTerrainHeight(10, 20);

// 设置坐标处的高度
ra3Map.SetTerrainHeight(50, 600, 300.5f);

// 根据高度信息, 自动更新地图中的`可通行性`信息
// 通常在完成一批高度修改后再调用
ra3Map.UpdatePassabilityMap();
```

### 纹理
```csharp
// 获取坐标处的纹理
string textureName = ra3Map.GetTileTexture(300, 550);

// 设置坐标处的纹理
ra3Map.SetTileTexture(10, 20, "BB_Gravel01");
// 也可以通过枚举来设置纹理
using Dreamness.Ra3.Map.Facade.enums;
ra3Map.SetTileTexture(10, 20, TextureEnum.BB_Gravel01.ToString());

// 自动纹理混合, 在有必要的情况下调用
ra3Map.AutoDetectBlendsEntireMap();
```
