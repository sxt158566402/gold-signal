with open('index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 修复 ft 函数 - 不加8小时，直接用浏览器本地时间
old_ft = """function ft(ts){
  var d=new Date(ts);
  var beijingTime = new Date(d.getTime() + (8 * 60 * 60 * 1000));
  var month = (beijingTime.getMonth()+1).toString().padStart(2,'0');
  var day = beijingTime.getDate().toString().padStart(2,'0');
  var hours = beijingTime.getHours().toString().padStart(2,'0');
  var mins = beijingTime.getMinutes().toString().padStart(2,'0');
  var secs = beijingTime.getSeconds().toString().padStart(2,'0');
  return month+'-'+day+' '+hours+':'+mins+':'+secs;
}"""

new_ft = """function ft(ts){
  var d = new Date(ts);
  var month = (d.getMonth()+1).toString().padStart(2,'0');
  var day = d.getDate().toString().padStart(2,'0');
  var hours = d.getHours().toString().padStart(2,'0');
  var mins = d.getMinutes().toString().padStart(2,'0');
  var secs = d.getSeconds().toString().padStart(2,'0');
  return month+'-'+day+' '+hours+':'+mins+':'+secs;
}"""

content = content.replace(old_ft, new_ft)

# 同样修复 checkRiskAlerts 里的北京时间转换
old_risk = """  // 周五晚上 20:00-24:00 风险提醒（强制北京时间）
  var beijingNow = new Date(now.getTime() + (8 * 60 * 60 * 1000));
  var beijingDay = beijingNow.getUTCDay();
  var beijingHour = beijingNow.getUTCHours();"""

new_risk = """  // 周五晚上 20:00-24:00 风险提醒（北京时间）
  var beijingDay = now.getDay();
  var beijingHour = now.getHours();"""

content = content.replace(old_risk, new_risk)

# 修复经济数据检测
old_econ = """    // 筛选今天或明天的高影响经济数据（北京时间）
    var beijingNow = new Date(now.getTime() + (8 * 60 * 60 * 1000));
    var today = beijingNow.toISOString().split('T')[0];
    var tomorrow = new Date(beijingNow.getTime() + 86400000).toISOString().split('T')[0];"""

new_econ = """    // 筛选今天或明天的高影响经济数据
    var today = now.toISOString().split('T')[0];
    var tomorrow = new Date(now.getTime() + 86400000).toISOString().split('T')[0];"""

content = content.replace(old_econ, new_econ)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("done")
