---
name: csharp_runner
description: 执行csharp代码
---

# C# Runner
用于执行c#代码  
base_url: http://127.0.0.1:30033

## 执行c#源文件
api: /api/csharpscript/run/file  
接受POST请求  
接受json数据, 共2个字段:
- filePath  必填, 源文件路径
- workingDirectory 可选, 工作路径

## 执行c#代码
api: /api/csharpscript/run/code
接受POST请求
接受json数据, 共2个字段:
- code  必填, c#源码
- workingDirectory 可选, 工作路径