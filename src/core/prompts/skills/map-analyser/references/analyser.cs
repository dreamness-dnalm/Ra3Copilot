using System.Text.RegularExpressions;
using Dreamness.Ra3.Map.Facade.Core;
using Dreamness.Ra3.Map.Facade.Util;
using Dreamness.Ra3.Map.Parser.Asset.Impl.GameObject;


float OreRefineryDistance = 180f;

Regex PlayerStartPattern = new(@"^Player_(\d+)_Start$", RegexOptions.Compiled);

var ra3Map = Ra3MapFacade.Open(Ra3PathUtil.RA3MapFolder, "###MAP_NAME###");

PrintSection("玩家出生点位置");
foreach (var wp in ra3Map.GetWaypoints()
                .Where(w => PlayerStartPattern.IsMatch(w.WaypointName))
                .OrderBy(w => w.WaypointName))
{
    var pos = wp.Position;
    Console.WriteLine($"{wp.WaypointName}: ({pos.X:F1}, {pos.Y:F1})");
}

PrintSection("油井位置");
foreach (var unit in ra3Map.GetUnitObjects()
                .Where(o => o.TypeName == "OilDerrick")
                .OrderBy(o => o.Position.X)
                .ThenBy(o => o.Position.Y))
{
    var pos = unit.Position;
    Console.WriteLine($"({pos.X:F1}, {pos.Y:F1})");
}

PrintSection("观测站位置");
foreach (var unit in ra3Map.GetUnitObjects()
                .Where(o => o.TypeName == "ObservationPostTechStructure")
                .OrderBy(o => o.Position.X)
                .ThenBy(o => o.Position.Y))
{
    var pos = unit.Position;
    Console.WriteLine($"({pos.X:F1}, {pos.Y:F1})");
}

PrintSection("矿脉及最佳矿场位置");
var oreNodes = ra3Map.GetUnitObjects()
    .Where(o => o.TypeName == "OreNode")
    .OrderBy(o => o.Position.X)
    .ThenBy(o => o.Position.Y)
    .ToList();

for (var i = 0; i < oreNodes.Count; i++)
{
    var ore = oreNodes[i];
    var orePos = ore.Position;
    var refPos = CalcBestOreRefineryPosition(ore);
    Console.WriteLine(
        $"矿脉#{i + 1}: ({orePos.X:F1}, {orePos.Y:F1}) -> 矿场: ({refPos.X:F1}, {refPos.Y:F1})");
}

        PrintSection("核心单位列表");
        List<string> objectFetchWhiteList = new List<string>()
            { "OreNode", "ObservationPostTechStructure", "OilDerrick" };
        var mapObjectList = ra3Map.ra3Map.Context.ObjectsListAsset.MapObjectList;
        for (var i = 0; i < mapObjectList.Count; i++)
        {
            var mapObject = mapObjectList[i];
            var typeName = mapObject.TypeName;
            if (objectFetchWhiteList.Contains(typeName))
            {
                Console.WriteLine($"{i + 1} th: {typeName} | ({mapObject.Position.X:F1}, {mapObject.Position.Y:F1})");
            }

        }


(float X, float Y) CalcBestOreRefineryPosition(UnitObjectWrap oreNode)
{
    var oreAngle = Normalize180(oreNode.Angle);
    var rad = oreAngle * MathF.PI / 180f;
    var x = oreNode.Position.X + OreRefineryDistance * MathF.Cos(rad);
    var y = oreNode.Position.Y + OreRefineryDistance * MathF.Sin(rad);
    return (x, y);
}

float Normalize180(float angle)
{
    angle %= 360f;
    if (angle <= -180f)
        angle += 360f;
    else if (angle > 180f)
        angle -= 360f;
    return angle;
}

void PrintSection(string title)
{
    Console.WriteLine();
    Console.WriteLine($"======== {title} ========");
}
