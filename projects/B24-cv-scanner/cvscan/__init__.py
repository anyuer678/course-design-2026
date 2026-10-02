"""B24-cv-scanner —— 文档扫描仪：边缘检测 → 透视变换 → 二值化（计算机视觉）

    synth.py     合成"文档照片"：渲染顶视文档（含文字掩码真值）→ 按已知四角透视"拍照"
    detect.py    Canny → 形态学闭 → findContours → approxPolyDP → 角点排序；拒识带原因
    rectify.py   四对点透视变换（getPerspectiveTransform + warpPerspective）
    binarize.py  Otsu 全局阈值 vs 自适应局部阈值（对真值掩码量一致率）
    pipeline.py  scan()：检测 → 还原 → 二值化，失败带原因返回

依赖：opencv-python（本机已装 cv2 4.13.0）+ numpy（已装 2.4.6）——**零安装**。
"""
