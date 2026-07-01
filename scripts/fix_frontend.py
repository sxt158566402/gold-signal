import re

with open('/opt/gold-signal/frontend/index.html', 'r') as f:
    content = f.read()

# 1. 删除多余的 }
old1 = "    swDetail.innerHTML = html;\n  }\n  }"
new1 = "    swDetail.innerHTML = html;\n  }"
if old1 in content:
    content = content.replace(old1, new1, 1)
    print("FIX1: removed extra }")
else:
    print("FIX1: no extra } found")

# 2. 更新等待信号提示语
old2 = '\u7cfb\u7d71\u76e3\u63a7\u4e2d\uff0c\u56de\u8e29\u6a6a\u76e4\u5f8c\u81ea\u52d5\u63d0\u793a'
new2 = '\u7cfb\u7d71\u76e3\u63a7\u4e2d\uff0c\u8da8\u52e2\u78ba\u8a8d+\u56de\u8e29\u4f01\u7a69\u5f8c\u81ea\u52d5\u63d0\u793a'
if old2 in content:
    content = content.replace(old2, new2, 1)
    print("FIX2: updated wait text")

# 3. 更新做多信号消息
old3 = "var msg = s.reason.indexOf('\u56de\u8e29\u6a6a\u76e4') >= 0\n          ? '\u6ce8\u610f\uff01\u4e0a\u6f32\u8da8\u52e2\u56de\u8e29\u6a6a\u76e4\uff0c\u505a\u591a\u4fe1\u865f\uff01\u9032\u5834\u50f9' + f(s.price) + '\uff0c\u6b62\u640d' + f(lSL) + '\uff0c\u6b62\u76c8' + f(lTP) + '\uff01'\n          : '\u505a\u591a\u4fe1\u865f\uff01\u9032\u5834\u50f9' + f(s.price) + '\uff0c\u6b62\u640d' + f(lSL) + '\uff0c\u8a18\u5f97\u6b62\u640d\uff01'"
new3 = "var msg = s.reason.indexOf('\u6a21\u5f0f') >= 0\n          ? '\u6ce8\u610f\uff01\u505a\u591a\u4fe1\u865f\uff01' + s.reason.split('|')[0] + ' \u9032\u5834\u50f9' + f(s.price) + '\uff0c\u6b62\u640d' + f(lSL) + '\uff0c\u6b62\u76c8' + f(lTP) + '\uff01'\n          : '\u505a\u591a\u4fe1\u865f\uff01\u9032\u5834\u50f9' + f(s.price) + '\uff0c\u6b62\u640d' + f(lSL) + '\uff0c\u8a18\u5f97\u6b62\u640d\uff01'"
if old3 in content:
    content = content.replace(old3, new3, 1)
    print("FIX3: updated long msg")

# 4. 更新做空信号消息
old4 = "var msg = s.reason.indexOf('\u56de\u8e29\u6a6a\u76e4') >= 0\n          ? '\u6ce8\u610f\uff01\u4e0b\u8dcc\u8da8\u52e2\u56de\u8e29\u6a6a\u76e4\uff0c\u505a\u7a7a\u4fe1\u865f\uff01\u9032\u5834\u50f9' + f(s.price) + '\uff0c\u6b62\u640d' + f(sSL) + '\uff0c\u6b62\u76c8' + f(sTP) + '\uff01'\n          : '\u505a\u7a7a\u4fe1\u865f\uff01\u9032\u5834\u50f9' + f(s.price) + '\uff0c\u6b62\u640d' + f(sSL) + '\uff0c\u8a18\u5f97\u6b62\u640d\uff01'"
new4 = "var msg = s.reason.indexOf('\u6a21\u5f0f') >= 0\n          ? '\u6ce8\u610f\uff01\u505a\u7a7a\u4fe1\u865f\uff01' + s.reason.split('|')[0] + ' \u9032\u5834\u50f9' + f(s.price) + '\uff0c\u6b62\u640d' + f(sSL) + '\uff0c\u6b62\u76c8' + f(sTP) + '\uff01'\n          : '\u505a\u7a7a\u4fe1\u865f\uff01\u9032\u5834\u50f9' + f(s.price) + '\uff0c\u6b62\u640d' + f(sSL) + '\uff0c\u8a18\u5f97\u6b62\u640d\uff01'"
if old4 in content:
    content = content.replace(old4, new4, 1)
    print("FIX4: updated short msg")

with open('/opt/gold-signal/frontend/index.html', 'w') as f:
    f.write(content)
print("SAVED")
