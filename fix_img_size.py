with open('index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 运势区域的小图：80x80 → 120x120，去掉圆形裁剪
content = content.replace(
    'width:80px;height:80px;border-radius:50%;border:2px solid rgba(138,43,226,.5);margin-bottom:8px',
    'width:120px;height:120px;border-radius:12px;border:2px solid rgba(138,43,226,.5);margin-bottom:8px;object-fit:cover'
)

# 弹窗里的大图：100x100 → 200x200，去掉圆形裁剪
content = content.replace(
    'width:100px;height:100px;border-radius:50%;border:2px solid rgba(138,43,226,.5)',
    'width:200px;height:200px;border-radius:12px;border:2px solid rgba(138,43,226,.5);object-fit:cover'
)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("done")
