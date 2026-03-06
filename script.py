# -*- coding: utf-8 -*-
"""
LEVEL ADJUSTER (SEMI-SILENT):
- Inputs: Enabled (Offset).
- Outputs: Disabled (No final report window).
- Works on: Sections & Elevations.
"""
from pyrevit import revit, DB, forms

# --- CẤU HÌNH ---
doc = revit.doc
uidoc = revit.uidoc

def mm_to_ft(mm_val):
    return mm_val / 304.8

def get_views_smart():
    """Chỉ lấy View Mặt đứng hoặc Mặt cắt."""
    sel_ids = uidoc.Selection.GetElementIds()
    selected_views = []
    
    def is_valid_view(v):
        return not v.IsTemplate and v.ViewType in [DB.ViewType.Section, DB.ViewType.Elevation]

    if sel_ids:
        for eid in sel_ids:
            el = doc.GetElement(eid)
            if isinstance(el, DB.Viewport):
                view = doc.GetElement(el.ViewId)
                if view and is_valid_view(view): selected_views.append(view)
            elif isinstance(el, DB.View) and is_valid_view(el):
                selected_views.append(el)
                
    # Nếu danh sách rỗng (do không chọn gì hoặc đang chọn đối tượng khác như Level, Grid)
    # thì tự động lấy view hiện hành nếu view đó hợp lệ.
    if not selected_views:
        if isinstance(doc.ActiveView, DB.View) and is_valid_view(doc.ActiveView):
            selected_views.append(doc.ActiveView)
            
    return selected_views

def to_view_cs(point, view_transform):
    """World -> View Local"""
    return view_transform.Inverse.OfPoint(point)

def to_world_cs(point, view_transform):
    """View Local -> World"""
    return view_transform.OfPoint(point)

def main_level_no_report():
    # 1. Chọn View
    views = get_views_smart()
    if not views:
        forms.alert("Vui lòng chọn Viewport (Mặt đứng/Mặt cắt) hoặc mở View.")
        return

    # 2. Nhập Offset (Vẫn hiện)
    res = forms.ask_for_string(
        default="15",
        prompt="Nhập khoảng cách Offset (mm):\n(Kéo dài 2 đầu Trái/Phải)",
        title="Level Adjuster"
    )
    if not res: return
    try:
        sheet_offset_mm = float(res)
    except: return

    # 3. Xử lý (Chạy ngầm)
    t = DB.Transaction(doc, "Adjust Levels")
    t.Start()
    
    try:
        for view in views:
            # Bật Crop
            if not view.CropBoxActive:
                view.CropBoxActive = True
                doc.Regenerate()

            bbox = view.CropBox
            if not bbox: continue

            b_min = bbox.Min # Góc dưới trái
            b_max = bbox.Max # Góc trên phải
            v_trans = bbox.Transform
            view_scale = view.Scale
            offset = mm_to_ft(sheet_offset_mm * view_scale)

            levels = DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Level).ToElements()

            for level in levels:
                try:
                    # Fix Scope Box
                    p_scope = level.LookupParameter("Scope Box") 
                    if p_scope and p_scope.AsElementId() != DB.ElementId.InvalidElementId:
                         p_scope.Set(DB.ElementId.InvalidElementId)
                    
                    # Set 2D Extents
                    level.SetDatumExtentType(DB.DatumEnds.End0, view, DB.DatumExtentType.ViewSpecific)
                    level.SetDatumExtentType(DB.DatumEnds.End1, view, DB.DatumExtentType.ViewSpecific)
                    
                    # Get Curve
                    curves = level.GetCurvesInView(DB.DatumExtentType.ViewSpecific, view)
                    if not curves: continue
                    level_curve = curves[0]
                    if not isinstance(level_curve, DB.Line): continue
                    
                    # Logic BoundingBox (Trái/Phải)
                    p1 = to_view_cs(level_curve.GetEndPoint(0), v_trans)
                    p2 = to_view_cs(level_curve.GetEndPoint(1), v_trans)
                    
                    if p1.X < p2.X:
                        pt_left, pt_right = p1, p2
                        swap = False
                    else:
                        pt_left, pt_right = p2, p1
                        swap = True
                        
                    # Tính toán X mới (Reset về mép Crop + Offset)
                    new_x_left = b_min.X - offset
                    new_x_right = b_max.X + offset
                    
                    new_left = DB.XYZ(new_x_left, pt_left.Y, pt_left.Z)
                    new_right = DB.XYZ(new_x_right, pt_right.Y, pt_right.Z)
                    
                    # Apply
                    if swap:
                        w_p1 = to_world_cs(new_right, v_trans)
                        w_p2 = to_world_cs(new_left, v_trans)
                    else:
                        w_p1 = to_world_cs(new_left, v_trans)
                        w_p2 = to_world_cs(new_right, v_trans)

                    if w_p1.DistanceTo(w_p2) > mm_to_ft(10):
                        new_line = DB.Line.CreateBound(w_p1, w_p2)
                        
                        if not new_line.Direction.IsAlmostEqualTo(level_curve.Direction):
                             new_line = DB.Line.CreateBound(w_p2, w_p1)

                        level.SetCurveInView(DB.DatumExtentType.ViewSpecific, view, new_line)

                except:
                    pass 

        t.Commit()
        
        # Làm mới màn hình ngay lập tức
        uidoc.RefreshActiveView()

    except:
        t.RollBack()

if __name__ == '__main__':
    main_level_no_report()