import re

with open('index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 修复黑色星期五检测，强制使用北京时间
old_code = """  // 周五晚上 20:00-24:00 风险提醒
  if(now.getDay() === 5 && now.getHours() >= 20){
    risks.push('🖤 <b>黑色星期五</b>：今晚波动极大，建议观望或轻仓！');
    isRiskDay = true;
  }"""

new_code = """  // 周五晚上 20:00-24:00 风险提醒（强制北京时间）
  var beijingNow = new Date(now.getTime() + (8 * 60 * 60 * 1000));
  var beijingDay = beijingNow.getUTCDay();
  var beijingHour = beijingNow.getUTCHours();
  if(beijingDay === 5 && beijingHour >= 20){
    risks.push('🖤 <b>黑色星期五</b>：今晚波动极大，建议观望或轻仓！');
    isRiskDay = true;
  }"""

content = content.replace(old_code, new_code)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ 已修复黑色星期五检测，强制使用北京时间")
