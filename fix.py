import re

with open('index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 修复 ft 函数，显示完整的北京时间（日期+时间）
old_ft = "function ft(ts){var d=new Date(ts);var beijingTime = new Date(d.getTime() + (8 * 60 * 60 * 1000));return beijingTime.getHours().toString().padStart(2,'0')+':'+beijingTime.getMinutes().toString().padStart(2,'0')+':'+beijingTime.getSeconds().toString().padStart(2,'0');}"

new_ft = """function ft(ts){
  var d=new Date(ts);
  var beijingTime = new Date(d.getTime() + (8 * 60 * 60 * 1000));
  var month = (beijingTime.getMonth()+1).toString().padStart(2,'0');
  var day = beijingTime.getDate().toString().padStart(2,'0');
  var hours = beijingTime.getHours().toString().padStart(2,'0');
  var mins = beijingTime.getMinutes().toString().padStart(2,'0');
  var secs = beijingTime.getSeconds().toString().padStart(2,'0');
  return month+'-'+day+' '+hours+':'+mins+':'+secs;
}"""

content = content.replace(old_ft, new_ft)

# 也修复 ft1 函数
old_ft1 = "function ft1(ts){var d=new Date(ts);return d.getFullYear()+'-'+(d.getMonth()+1).toString().padStart(2,'0')+'-'+d.getDate().toString().padStart(2,'0')+' '+d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');}"

new_ft1 = """function ft1(ts){
  var d=new Date(ts);
  var beijingTime = new Date(d.getTime() + (8 * 60 * 60 * 1000));
  return beijingTime.getFullYear()+'-'+(beijingTime.getMonth()+1).toString().padStart(2,'0')+'-'+beijingTime.getDate().toString().padStart(2,'0')+' '+beijingTime.getHours().toString().padStart(2,'0')+':'+beijingTime.getMinutes().toString().padStart(2,'0');
}"""

content = content.replace(old_ft1, new_ft1)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ 修复完成")
