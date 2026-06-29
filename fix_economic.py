import re

with open('index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 修复经济数据检测，使用北京时间
old_code = """    // 筛选今天或明天的高影响经济数据
    var today = now.toISOString().split('T')[0];
    var tomorrow = new Date(now.getTime() + 86400000).toISOString().split('T')[0];"""

new_code = """    // 筛选今天或明天的高影响经济数据（北京时间）
    var beijingNow = new Date(now.getTime() + (8 * 60 * 60 * 1000));
    var today = beijingNow.toISOString().split('T')[0];
    var tomorrow = new Date(beijingNow.getTime() + 86400000).toISOString().split('T')[0];"""

content = content.replace(old_code, new_code)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ 已修复经济数据检测，使用北京时间")
