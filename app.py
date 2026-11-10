import streamlit as st
import random, json, os
from collections import Counter

st.set_page_config(page_title="Морской бой", page_icon="🚢", layout="wide")

SIZE = 10
FLEET = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]  # классика: 1x4, 2x3, 3x2, 4x1
LETTERS = "АБВГДЕЖЗИК"
LATIN = "ABVGDEZIK"
MEMORY_FILE = "battleship_memory.json"
SHIP_NAMES = {4: "Линкор (4 палубы)", 3: "Крейсер (3 палубы)",
              2: "Эсминец (2 палубы)", 1: "Катер (1 палуба)"}

# ================= ЛОГИКА ИГРЫ =================
def can_place(occ, r, c, ln, horiz):
    cells = [(r, c + i) for i in range(ln)] if horiz else [(r + i, c) for i in range(ln)]
    for (rr, cc) in cells:
        if not (0 <= rr < SIZE and 0 <= cc < SIZE):
            return False
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                rr2, cc2 = rr + dr, cc + dc
                if 0 <= rr2 < SIZE and 0 <= cc2 < SIZE and occ[rr2][cc2]:
                    return False
    return True

def place_ship(occ, r, c, ln, horiz):
    cells = [(r, c + i) for i in range(ln)] if horiz else [(r + i, c) for i in range(ln)]
    for (rr, cc) in cells:
        occ[rr][cc] = True
    return cells

def random_fleet(rng):
    occ = [[False] * SIZE for _ in range(SIZE)]
    ships = []
    for ln in FLEET:
        while True:
            horiz = rng.random() < 0.5
            r = rng.randrange(SIZE - (0 if horiz else ln - 1))
            c = rng.randrange(SIZE - (ln - 1 if horiz else 0))
            if can_place(occ, r, c, ln, horiz):
                ships.append(place_ship(occ, r, c, ln, horiz))
                break
    return ships

def shoot(ships_alive, r, c):
    for i, sh in enumerate(ships_alive):
        if sh and (r, c) in sh:
            sh.remove((r, c))
            return ("sunk" if not sh else "hit"), i
    return "miss", None

def mark_sunk(ship_cells, known_hits, known_miss):
    # сначала все клетки корабля — в попадания, потом ореол
    for (rr, cc) in ship_cells:
        known_hits.add((rr, cc))
    for (rr, cc) in ship_cells:
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                r2, c2 = rr + dr, cc + dc
                if 0 <= r2 < SIZE and 0 <= c2 < SIZE and (r2, c2) not in known_hits:
                    known_miss.add((r2, c2))

# ================= ИИ =================
class AI:
    def __init__(self, memory_file=MEMORY_FILE):
        self.memory_file = memory_file
        self.counts = [[0] * SIZE for _ in range(SIZE)]
        self.games_seen = 0
        self.load()

    def load(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file) as f:
                    data = json.load(f)
                self.counts = data["counts"]
                self.games_seen = data["games_seen"]
            except (ValueError, KeyError):
                pass

    def save(self):
        try:
            with open(self.memory_file, "w") as f:
                json.dump({"counts": self.counts, "games_seen": self.games_seen}, f)
        except OSError:
            pass  # на облачном сервере файлы могут быть только для чтения

    def learn_from_game(self, enemy_ships):
        for sh in enemy_ships:
            for (r, c) in sh:
                self.counts[r][c] += 1
        self.games_seen += 1
        self.save()

    def _prior(self, r, c):
        if self.games_seen == 0:
            return 1.0
        return 1.0 + 3.0 * (self.counts[r][c] / self.games_seen) / 0.2

    def choose(self, board, remaining):
        dens = [[0.0] * SIZE for _ in range(SIZE)]
        for ln in remaining:
            for r in range(SIZE - ln + 1):
                for c in range(SIZE - ln + 1):
                    for horiz in (True, False):
                        if horiz:
                            if c + ln > SIZE: continue
                            cells = [(r, c + i) for i in range(ln)]
                        else:
                            if r + ln > SIZE: continue
                            cells = [(r + i, c) for i in range(ln)]
                        ok, w, has_hit = True, 1.0, False
                        for (rr, cc) in cells:
                            v = board[rr][cc]
                            if v in (1, 3):
                                ok = False; break
                            if v == 2:
                                has_hit = True
                        if not ok: continue
                        for (rr, cc) in cells:
                            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                                rr2, cc2 = rr + dr, cc + dc
                                if 0 <= rr2 < SIZE and 0 <= cc2 < SIZE and board[rr2][cc2] == 3:
                                    ok = False; break
                            if not ok: break
                        if not ok: continue
                        for (rr, cc) in cells:
                            if board[rr][cc] == 0:
                                w *= self._prior(rr, cc)
                        if has_hit:
                            w *= 50
                        for (rr, cc) in cells:
                            if board[rr][cc] == 0:
                                dens[rr][cc] += w
        best, br, bc = -1, -1, -1
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] == 0 and dens[r][c] > best:
                    best, br, bc = dens[r][c], r, c
        if best == -1:
            for r in range(SIZE):
                for c in range(SIZE):
                    if board[r][c] == 0:
                        return r, c
        return br, bc

def ai_board_for(known_miss, known_hits, my_full, my_alive):
    board = [[0] * SIZE for _ in range(SIZE)]
    for (r, c) in known_miss: board[r][c] = 1
    for (r, c) in known_hits: board[r][c] = 2
    for sh, full in zip(my_alive, my_full):
        if full and not sh:
            for (rr, cc) in full: board[rr][cc] = 3
    return board

# ================= СОСТОЯНИЕ =================
def reset_game():
    ss = st.session_state
    ss.screen = "setup"
    ss.placed = []
    ss.occ = [[False] * SIZE for _ in range(SIZE)]
    ss.my_full = None
    ss.enemy_full = None
    ss.p_hits, ss.p_miss = set(), set()
    ss.a_hits, ss.a_miss = set(), set()
    ss.turn = "player"
    ss.finished = None
    ss.last_msg = ""

if "screen" not in st.session_state:
    reset_game()
    st.session_state.ai = AI()

ss = st.session_state

def take_click(prefix):
    key = f"{prefix}_clicked"
    val = ss[key] if key in ss else None
    if key in ss:
        del ss[key]
    return val

# ================= ОТРИСОВКА ДОСКИ =================
def cell_char(hits, misses, ships, reveal, r, c):
    if (r, c) in hits: return "X"
    if (r, c) in misses: return "·"
    if reveal and (r, c) in ships: return "■"
    return " "

def draw_grid(hits, misses, ship_cells, reveal, prefix, clickable=False):
    head = st.columns([0.45] + [1] * SIZE)
    head[0].write("")
    for i, L in enumerate(LETTERS):
        head[i + 1].markdown(f"**{L}**")
    ship_cells = set(ship_cells or [])
    for r in range(SIZE):
        cols = st.columns([0.45] + [1] * SIZE)
        cols[0].markdown(f"**{r + 1}**")
        for c in range(SIZE):
            ch = cell_char(hits, misses, ship_cells, reveal, r, c)
            btn = cols[c + 1].button(ch if ch else " ", key=f"{prefix}_{r}_{c}",
                                     use_container_width=True,
                                     disabled=not clickable)
            if btn:
                ss[f"{prefix}_clicked"] = (r, c)

# ================= ЭКРАН РАССТАНОВКИ =================
if ss.screen == "setup":
    st.title("🚢 Морской бой")
    st.caption("Классический флот: 1×4, 2×3, 3×2, 4×1. Корабли не должны соприкасаться.")

    need = Counter(FLEET)
    have = Counter(len(s) for s in ss.placed)
    rem = need - have  # остаются только положительные количества

    left, right = st.columns([1, 1])
    with left:
        if rem:
            label_to_len = {f"{SHIP_NAMES[l]} — осталось {rem[l]}": l
                            for l in sorted(rem, reverse=True)}
            sel = st.selectbox("Какой корабль ставим:", list(label_to_len))
            ln = label_to_len[sel]
            horiz = st.radio("Направление:", ["вправо (г)", "вниз (в)"]) == "вправо (г)"
            st.write("Кликни по клетке — здесь будет нос корабля.")
        else:
            st.success("Флот расставлен! Жми «В бой».")
    with right:
        if st.button("🎲 Случайная расстановка (авто)", use_container_width=True):
            fleet = random_fleet(random.Random())
            occ = [[False] * SIZE for _ in range(SIZE)]
            for sh in fleet:
                for (r, c) in sh:
                    occ[r][c] = True
            ss.placed = [list(s) for s in fleet]
            ss.occ = occ
            st.rerun()

    placed_cells = [cell for sh in ss.placed for cell in sh]
    draw_grid(set(), set(), placed_cells, True, "place", clickable=bool(rem))

    clicked = take_click("place")
    if clicked and rem:
        r, c = clicked
        if can_place(ss.occ, r, c, ln, horiz):
            cells = place_ship(ss.occ, r, c, ln, horiz)
            ss.placed.append(cells)
            st.rerun()
        else:
            st.warning("Здесь нельзя: корабль вылезает за поле или касается другого.")

    if not rem and st.button("⚔️ В бой!", type="primary"):
        ss.my_full = [list(s) for s in ss.placed]
        ss.enemy_full = random_fleet(random.Random())
        ss.screen = "battle"
        ss.last_msg = "Твой ход — кликни по клетке доски противника."
        st.rerun()

# ================= ЭКРАН БОЯ =================
else:
    st.title("🚢 Морской бой")

    with st.expander("Правила и кнопки"):
        st.write("Попал или потопил — стреляешь снова, противник пропускает ход. "
                 "Промах — ход переходит ИИ. Клик по клетке правой доски — выстрел.")

    my_alive = [[cell for cell in sh if cell not in ss.a_hits] for sh in ss.my_full]
    enemy_alive = [[cell for cell in sh if cell not in ss.p_hits] for sh in ss.enemy_full]

    def finish(res):
        ss.finished = res
        ss.ai.learn_from_game(ss.enemy_full)

    if not any(enemy_alive):
        finish("win")
    elif not any(my_alive):
        finish("lose")

    if ss.finished:
        if ss.finished == "win":
            st.success("🏆 ПОБЕДА! Ты потопил весь флот ИИ")
        elif ss.finished == "surrender":
            st.warning("🏳 Ты сдался. Флот ИИ был здесь:")
        else:
            st.error("💀 ПОРАЖЕНИЕ. ИИ потопил твой флот")
        enemy_cells = set(c for sh in ss.enemy_full for c in sh)
        draw_grid(ss.p_hits, ss.p_miss, enemy_cells, True, "fin", clickable=False)
        st.write(f"Партий в памяти ИИ: {ss.ai.games_seen}")
        if st.button("🔄 Новая партия", type="primary"):
            reset_game()
            st.rerun()
        st.stop()

    # --- ход ИИ (автоматически, по одному выстрелу за перерисовку) ---
    if ss.turn == "ai":
        board = ai_board_for(ss.a_miss, ss.a_hits, ss.my_full, my_alive)
        remaining = [len(sh) for sh in my_alive if sh]
        r, c = ss.ai.choose(board, remaining)
        result, i = shoot(my_alive, r, c)
        if result == "miss":
            ss.a_miss.add((r, c))
            ss.last_msg = f"ИИ стрелял: {LETTERS[c]}{r + 1} — мимо 🌊"
            ss.turn = "player"
        elif result == "hit":
            ss.a_hits.add((r, c))
            ss.last_msg = f"ИИ стрелял: {LETTERS[c]}{r + 1} — попадание 💥 ИИ ходит снова"
        else:
            mark_sunk(ss.my_full[i], ss.a_hits, ss.a_miss)
            ss.last_msg = f"ИИ стрелял: {LETTERS[c]}{r + 1} — убил 🔥 {SHIP_NAMES[len(ss.my_full[i])]} потоплен"
        st.rerun()

    # --- ход игрока ---
    st.info(ss.last_msg)

    if st.button("🏳 Сдаться"):
        finish("surrender")
        st.rerun()

    lc, rc = st.columns(2)
    with lc:
        st.markdown("**Твоя доска**")
        my_cells = set(c for sh in ss.my_full for c in sh)
        draw_grid(ss.a_hits, ss.a_miss, my_cells, True, "own", clickable=False)
    with rc:
        st.markdown("**Доска противника**")
        draw_grid(ss.p_hits, ss.p_miss, set(), False, "atk", clickable=True)

    clicked = take_click("atk")
    if clicked:
        r, c = clicked
        result, i = shoot(enemy_alive, r, c)
        if result == "miss":
            ss.p_miss.add((r, c))
            ss.last_msg = f"Твой выстрел: {LETTERS[c]}{r + 1} — мимо 🌊 Ход переходит ИИ."
            ss.turn = "ai"
        elif result == "hit":
            ss.p_hits.add((r, c))
            ss.last_msg = f"Твой выстрел: {LETTERS[c]}{r + 1} — попадание 💥 Стреляй ещё!"
        else:
            mark_sunk(ss.enemy_full[i], ss.p_hits, ss.p_miss)
            ss.last_msg = f"Твой выстрел: {LETTERS[c]}{r + 1} — убил 🔥 Потоплен {SHIP_NAMES[len(ss.enemy_full[i])]}! Стреляй ещё!"
        st.rerun()
