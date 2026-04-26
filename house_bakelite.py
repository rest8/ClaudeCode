"""
バケラッタ建築風 3階建て邸宅 自動生成スクリプト for Blender 3.x / 4.x

使い方:
  1. Blender を起動し、Scripting タブを開く
  2. 新規テキスト > このファイルを Open
  3. Run Script  (もしくは:  blender --background --python house_bakelite.py )

仕様:
  敷地  : 200坪 (約 25m x 26.5m = 662.5m2)
  建物  : 3階建て / 延床 600m2 (各階 200m2, ガレージ3台込み)
  内訳  : 10LDK + 60畳リビング + 吹抜 + 中庭プール + 大階段 + ホームエレベーター
"""

import bpy
import bmesh
from math import radians
from mathutils import Vector

# ---------------------------------------------------------------------------
# 0.  Scene reset & helpers
# ---------------------------------------------------------------------------

def reset_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials,
                  bpy.data.lights,  bpy.data.cameras):
        for item in list(block):
            block.remove(item)


def make_material(name, rgba, roughness=0.5, metallic=0.0, emission=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if "Emission" in bsdf.inputs:
        bsdf.inputs["Emission"].default_value = (rgba[0], rgba[1], rgba[2], 1)
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = emission
    return mat


def add_box(name, location, size, material=None, collection=None):
    """中心 location, 寸法 size=(x,y,z) のボックスを作成"""
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (size[0]/2, size[1]/2, size[2]/2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if material:
        obj.data.materials.append(material)
    if collection:
        for c in obj.users_collection:
            c.objects.unlink(obj)
        collection.objects.link(obj)
    return obj


def boolean_diff(target, cutter):
    mod = target.modifiers.new("cut", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.object = cutter
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def new_collection(name):
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


# ---------------------------------------------------------------------------
# 1.  Materials
# ---------------------------------------------------------------------------

def build_materials():
    return {
        "concrete": make_material("Concrete",  (0.88, 0.87, 0.84, 1), 0.7),
        "wall_dk":  make_material("WallDark",  (0.18, 0.18, 0.20, 1), 0.6),
        "glass":    make_material("Glass",     (0.55, 0.75, 0.85, 0.15), 0.05, 0.0),
        "wood":     make_material("Wood",      (0.55, 0.35, 0.20, 1), 0.45),
        "tile":     make_material("Tile",      (0.92, 0.90, 0.85, 1), 0.25),
        "water":    make_material("Water",     (0.10, 0.40, 0.55, 1), 0.05, 0.2),
        "lawn":     make_material("Lawn",      (0.20, 0.45, 0.18, 1), 0.9),
        "asphalt":  make_material("Asphalt",   (0.15, 0.15, 0.15, 1), 0.85),
        "metal":    make_material("Metal",     (0.75, 0.75, 0.78, 1), 0.30, 1.0),
        "roof":     make_material("Roof",      (0.10, 0.10, 0.12, 1), 0.55),
        "accent":   make_material("Accent",    (0.85, 0.30, 0.15, 1), 0.5),
    }


# ---------------------------------------------------------------------------
# 2.  Site (敷地) ・ 中庭 ・ プール
# ---------------------------------------------------------------------------

PLOT_X, PLOT_Y = 25.0, 26.5         # 敷地寸法
H1, H2, H3     = 3.6, 3.3, 3.3       # 各階の階高
HOUSE_X, HOUSE_Y = 20.0, 10.0        # 建物 1フロア 200m2
HOUSE_OX, HOUSE_OY = -2.0, 7.0       # 建物中心の敷地内オフセット


def build_site(mat, col):
    add_box("Lot", (0, 0, -0.05), (PLOT_X, PLOT_Y, 0.10), mat["lawn"], col)

    # 駐車アプローチ (アスファルト)
    add_box("Driveway", (5.0, -3.0, 0.01),
            (8.0, 14.0, 0.05), mat["asphalt"], col)

    # 中庭 (タイル張り) ── 建物の南側
    courtyard = add_box("Courtyard", (-2.0, -5.0, 0.02),
                        (16.0, 12.0, 0.06), mat["tile"], col)

    # プール (中庭内) ── 床に凹みを作る
    pool_void = add_box("PoolVoid", (-4.0, -6.0, -0.6),
                        (8.0, 4.0, 1.4), None, col)
    boolean_diff(courtyard, pool_void)
    # プール水面
    add_box("PoolWater", (-4.0, -6.0, -0.05),
            (7.8, 3.8, 0.05), mat["water"], col)
    # プール内壁
    add_box("PoolFloor", (-4.0, -6.0, -1.25),
            (7.9, 3.9, 0.10), mat["tile"], col)


# ---------------------------------------------------------------------------
# 3.  Walls / Floors / Atrium / Stairs / Elevator / Garage
# ---------------------------------------------------------------------------

WALL_T = 0.20  # 壁厚


def shell(name, ox, oy, sx, sy, z0, z1, mat, col, hollow=True):
    """直方体の外殻を作る (hollow=True なら内部を BOOLEAN で抜く)"""
    cz = (z0 + z1) / 2
    h  = z1 - z0
    outer = add_box(name, (ox, oy, cz), (sx, sy, h), mat, col)
    if hollow:
        inner = add_box(name + "_void", (ox, oy, cz),
                        (sx - 2*WALL_T, sy - 2*WALL_T, h - 0.02),
                        None, col)
        boolean_diff(outer, inner)
    return outer


def punch_window(wall, cx, cy, cz, sx, sy, sz, col):
    cutter = add_box("winCut", (cx, cy, cz), (sx, sy, sz), None, col)
    boolean_diff(wall, cutter)


def floor_slab(name, ox, oy, sx, sy, z, t, mat, col):
    return add_box(name, (ox, oy, z + t/2), (sx, sy, t), mat, col)


def build_house(mat, col):
    OX, OY = HOUSE_OX, HOUSE_OY

    # ----- 各階の外殻 (コンクリート) ------------------------------------
    z0 = 0.0
    z1 = z0 + H1
    z2 = z1 + H2
    z3 = z2 + H3

    f1 = shell("F1_Shell", OX, OY, HOUSE_X, HOUSE_Y, z0, z1, mat["concrete"], col)
    f2 = shell("F2_Shell", OX, OY, HOUSE_X, HOUSE_Y, z1, z2, mat["concrete"], col)
    # 3F は南側を 4m セットバックしてバケラッタ的造形に
    f3 = shell("F3_Shell", OX, OY + 2.0, HOUSE_X, HOUSE_Y - 4.0,
               z2, z3, mat["concrete"], col)

    # 屋上スラブ
    floor_slab("RoofSlab", OX, OY + 2.0, HOUSE_X, HOUSE_Y - 4.0,
               z3, 0.20, mat["roof"], col)
    # 2F セットバック部分の屋上 (テラス用)
    floor_slab("F2_RoofTerrace", OX, OY - 3.0, HOUSE_X, 4.0,
               z2, 0.15, mat["tile"], col)

    # ----- 大窓 (南面 1F リビング, 2F 共用廊下, 3F マスター) ------------
    # 1F リビング 南面ガラス
    punch_window(f1, OX - 3.0, OY - HOUSE_Y/2, 1.6 + z0,
                 10.0, WALL_T*4, 2.4, col)
    # 2F 南面 連窓
    punch_window(f2, OX, OY - HOUSE_Y/2, 1.4 + z1,
                 14.0, WALL_T*4, 1.8, col)
    # 3F 南面 マスター
    punch_window(f3, OX, OY + 2.0 - (HOUSE_Y-4.0)/2, 1.4 + z2,
                 10.0, WALL_T*4, 2.0, col)

    # 玄関 (東面 1F)
    punch_window(f1, OX + HOUSE_X/2, OY + 2.0, 1.1 + z0,
                 WALL_T*4, 1.4, 2.2, col)

    # ガレージ開口 3台 (北面 1F)  → 3.0m 幅 × 2.4m 高 × 3 連
    for i, gx in enumerate([-7.5, -4.3, -1.1]):
        punch_window(f1, OX + gx, OY + HOUSE_Y/2, 1.2 + z0,
                     2.8, WALL_T*4, 2.4, col)

    # ガラスファサード (1F リビング南)
    add_box("LivingGlass",
            (OX - 3.0, OY - HOUSE_Y/2 + 0.02, z0 + 1.6),
            (9.8, 0.05, 2.3), mat["glass"], col)

    # ----- 床スラブ (各階の床) -----------------------------------------
    floor_slab("F1_Floor", OX, OY, HOUSE_X - 0.4, HOUSE_Y - 0.4,
               z0, 0.10, mat["wood"], col)
    f2_floor = floor_slab("F2_Floor", OX, OY, HOUSE_X - 0.4, HOUSE_Y - 0.4,
                          z1, 0.20, mat["wood"], col)
    f3_floor = floor_slab("F3_Floor", OX, OY + 2.0,
                          HOUSE_X - 0.4, HOUSE_Y - 4.4,
                          z2, 0.20, mat["wood"], col)

    # ----- 吹抜 (リビング上) → F2 床に開口 ---------------------------
    atrium_void = add_box("AtriumVoid",
                          (OX - 3.0, OY - 1.5, z1 + 0.1),
                          (8.0, 5.0, 0.6), None, col)
    boolean_diff(f2_floor, atrium_void)

    # ----- 内部間仕切 (10LDK) -----------------------------------------
    build_partitions(OX, OY, z0, z1, z2, z3, mat, col)

    # ----- 大階段 (吹抜の脇) ------------------------------------------
    build_grand_stairs(OX + 4.0, OY - 1.5, z0, z2, mat, col)

    # ----- ホームエレベーター ------------------------------------------
    build_elevator(OX + 7.5, OY + 3.0, z0, z3, mat, col)

    # ----- ガレージ床 & シャッター枠 -----------------------------------
    add_box("GarageFloor", (OX - 4.3, OY + 3.5, z0 + 0.05),
            (10.0, 6.5, 0.10), mat["asphalt"], col)


def build_partitions(OX, OY, z0, z1, z2, z3, mat, col):
    """各階の間仕切壁を配置 (簡略表現)"""
    t = 0.12

    # ---- 1F: 玄関 / 60畳LDK / 居室1 / 水回り --------------------------
    # LDK と玄関ホールの間
    add_box("F1_Wall_A",
            (OX + 4.0, OY + 1.5, z0 + H1/2),
            (t, 7.0, H1 - 0.2), mat["wall_dk"], col)
    # ガレージ間仕切
    add_box("F1_Wall_Garage",
            (OX, OY + 0.0, z0 + H1/2),
            (HOUSE_X - 0.4, t, H1 - 0.2), mat["wall_dk"], col)
    # 居室1 (西端)
    add_box("F1_Wall_R1",
            (OX - 5.0, OY - 1.5, z0 + H1/2),
            (t, 5.0, H1 - 0.2), mat["wall_dk"], col)

    # ---- 2F: 5居室 + バス --------------------------------------------
    y_mid = OY
    # 廊下の北側壁
    add_box("F2_Wall_Hall",
            (OX, y_mid + 1.5, z1 + H2/2),
            (HOUSE_X - 0.6, t, H2 - 0.2), mat["wall_dk"], col)
    # 5室分の仕切
    for x in [-7.0, -3.5, 0.0, 3.5, 6.5]:
        add_box(f"F2_Wall_R_{x}",
                (OX + x, y_mid + 3.0, z1 + H2/2),
                (t, 3.0, H2 - 0.2), mat["wall_dk"], col)

    # ---- 3F: 4居室 + マスターバス ------------------------------------
    add_box("F3_Wall_Hall",
            (OX, OY + 3.5, z2 + H3/2),
            (HOUSE_X - 0.6, t, H3 - 0.2), mat["wall_dk"], col)
    for x in [-6.0, -1.5, 2.5, 6.0]:
        add_box(f"F3_Wall_R_{x}",
                (OX + x, OY + 5.0, z2 + H3/2),
                (t, 2.5, H3 - 0.2), mat["wall_dk"], col)


def build_grand_stairs(cx, cy, z_bottom, z_top, mat, col):
    """中央吹抜脇に配置する大階段 (1F→2F→3F の連続) を 2 段組で作成"""
    flights = [
        (z_bottom, z_bottom + H1),       # 1F → 2F
        (z_bottom + H1, z_top),          # 2F → 3F
    ]
    for fi, (zb, zt) in enumerate(flights):
        n = 18
        rise = (zt - zb) / n
        run  = 0.30
        total_len = n * run
        y_offset  = -total_len / 2 + (fi * 0.6)
        for i in range(n):
            zc = zb + rise * (i + 0.5)
            add_box(f"Step_{fi}_{i}",
                    (cx, cy + y_offset + run * i, zc),
                    (2.4, run, rise), mat["wood"], col)
        # 手すり (簡略)
        add_box(f"Rail_{fi}",
                (cx + 1.3, cy + y_offset + total_len/2, zb + (zt-zb)/2 + 0.95),
                (0.05, total_len, 0.05), mat["metal"], col)


def build_elevator(cx, cy, z_bottom, z_top, mat, col):
    """ホームエレベーター: シャフト + ケージ"""
    sx, sy = 1.6, 1.8
    # シャフト外殻 (ガラス塔)
    shaft = shell("ElevShaft", cx, cy, sx, sy,
                  z_bottom, z_top + 0.4, mat["glass"], col, hollow=True)
    # ケージ (1F に停車)
    add_box("ElevCage",
            (cx, cy, z_bottom + 1.1),
            (sx - 0.3, sy - 0.3, 2.2), mat["metal"], col)


# ---------------------------------------------------------------------------
# 4.  外構オブジェクト: 車3台 / プールサイドベンチ / 樹木
# ---------------------------------------------------------------------------

def build_cars(mat, col):
    OX = HOUSE_OX
    z = 0.7
    for i, gx in enumerate([-7.5, -4.3, -1.1]):
        body = add_box(f"Car{i}_Body", (OX + gx, HOUSE_OY + 4.5, z),
                       (1.9, 4.4, 1.4),
                       mat["accent"] if i == 1 else mat["wall_dk"], col)
        add_box(f"Car{i}_Cabin", (OX + gx, HOUSE_OY + 4.7, z + 0.7),
                (1.7, 2.4, 0.8), mat["glass"], col)


def build_garden(mat, col):
    # 中庭の縁にベンチ
    add_box("Bench1", (3.0, -2.0, 0.30), (3.0, 0.5, 0.4), mat["wood"], col)
    # 樹木 (球+幹)
    for x, y in [(10.5, 11.0), (-11.0, 10.5), (10.5, -11.5), (-11.0, -11.5)]:
        add_box(f"Trunk_{x}_{y}", (x, y, 1.2), (0.3, 0.3, 2.4), mat["wood"], col)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.6, location=(x, y, 3.4))
        crown = bpy.context.active_object
        crown.name = f"Crown_{x}_{y}"
        crown.data.materials.append(mat["lawn"])
        for c in crown.users_collection:
            c.objects.unlink(crown)
        col.objects.link(crown)


# ---------------------------------------------------------------------------
# 5.  Camera / Lighting
# ---------------------------------------------------------------------------

def build_camera_and_light():
    bpy.ops.object.camera_add(location=(34, -28, 18),
                              rotation=(radians(68), 0, radians(48)))
    cam = bpy.context.active_object
    cam.data.lens = 28
    bpy.context.scene.camera = cam

    # Sun
    bpy.ops.object.light_add(type='SUN', location=(20, -10, 30))
    sun = bpy.context.active_object
    sun.data.energy = 4.0
    sun.rotation_euler = (radians(55), radians(20), radians(35))

    # World HDRI (簡易グラデ)
    world = bpy.context.scene.world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.55, 0.70, 0.85, 1)
    bg.inputs["Strength"].default_value = 1.2

    # Render
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE_NEXT' \
        if 'BLENDER_EEVEE_NEXT' in {e.identifier for e in
            scene.render.bl_rna.properties['engine'].enum_items} \
        else 'BLENDER_EEVEE'
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080


# ---------------------------------------------------------------------------
# 6.  Main
# ---------------------------------------------------------------------------

def main():
    reset_scene()
    mat = build_materials()

    col_site   = new_collection("00_Site")
    col_house  = new_collection("10_House")
    col_garden = new_collection("20_Garden")

    build_site(mat, col_site)
    build_house(mat, col_house)
    build_cars(mat, col_garden)
    build_garden(mat, col_garden)
    build_camera_and_light()

    print("✔ バケラッタ邸 生成完了 — 延床 600m2 / 10LDK / 中庭プール付")


if __name__ == "__main__":
    main()
