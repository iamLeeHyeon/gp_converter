# Phase 1 기본 편집기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** alphaTab 악보에서 음표를 클릭해 선택하고, 사이드 패널에서 프렛·지속시간·이펙트·다이나믹을 편집하며 Undo/Redo와 3초 자동저장을 제공하는 기본 편집기를 구현한다.

**Architecture:** alphaTab `api.noteMouseDown` 이벤트로 음표를 선택 → EditPanel에서 값 변경 → `scoreApplier`가 `api.score`를 직접 수정 → `api.render()` 재호출 → ScoreSnapshot(JSON)을 Zustand 히스토리 스택에 push → 3초 debounce 후 `POST /files/{id}/sync` 서버 동기화 → PyGuitarPro가 GP5 재생성.

**Tech Stack:** FastAPI, PyGuitarPro 0.10.x, React 18 + TypeScript, alphaTab 1.x (`@coderline/alphatab`), Zustand 4, Vitest + @testing-library/react

## Global Constraints

- alphaTab: `@coderline/alphatab@^1.3` (버전 고정)
- ScoreSnapshot: `src/lib/scoreTypes.ts`에 정의, 모든 파일이 여기서 import
- 스트링 번호: ScoreSnapshot은 GP 컨벤션 (1=high E, 6=low E) — guitar-tab-omr 토큰(1=low E)과 다름, `snapshot_to_gp5`에서 7-strig 반전 안 함
- `snapshot_to_gp5`는 기존 `_fill_measure`, `_DUR_UNITS`, `_DUR_FILL_ORDER`를 재사용
- 비로그인(fileId=null)은 sync 호출 안 함 (로컬 편집만)
- 음표 추가 기본값: string=1, fret=0, duration=4
- Undo 히스토리 최대 100단계
- effect는 음표당 하나 (복합 불가)
- dynamic은 비트 레벨, 해당 비트의 모든 음표에 동일 velocity 적용

---

## File Map

| 상태 | 경로 | 역할 |
|------|------|------|
| 수정 | `app/pipeline/token_to_gp.py` | `snapshot_to_gp5()` 추가 |
| 신규 | `app/routers/edit.py` | `POST /files/{id}/sync` |
| 수정 | `app/main.py` | edit 라우터 등록 |
| 신규 | `tests/test_edit.py` | sync 엔드포인트 테스트 |
| 신규 | `frontend/src/lib/scoreTypes.ts` | ScoreSnapshot 타입 정의 |
| 신규 | `frontend/src/store/editorStore.ts` | 선택 상태 + 스냅샷 히스토리 |
| 신규 | `frontend/src/lib/scoreSerializer.ts` | alphaTab Score → ScoreSnapshot |
| 신규 | `frontend/src/lib/scoreApplier.ts` | ScoreSnapshot 편집 → alphaTab Score 적용 |
| 수정 | `frontend/src/lib/api.ts` | `syncFile()` 추가 |
| 신규 | `frontend/src/lib/useSyncFile.ts` | 자동저장 debounce 훅 |
| 신규 | `frontend/src/components/Editor/EditPanel.tsx` | 편집 UI 패널 |
| 수정 | `frontend/src/components/Editor/ScoreViewer.tsx` | noteMouseDown 연결 + EditPanel 렌더링 |
| 수정 | `frontend/src/App.tsx` | 3컬럼 레이아웃 |

---

## Task 1: Backend — snapshot_to_gp5()

**Files:**
- Modify: `app/pipeline/token_to_gp.py`
- Modify: `tests/test_token_to_gp.py`

**Interfaces:**
- Produces: `snapshot_to_gp5(snapshot: dict, out_path: str) -> str`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_token_to_gp.py` 파일 끝에 추가:

```python
SIMPLE_SNAPSHOT = {
    "tracks": [{
        "measures": [{
            "timeSignature": {"num": 4, "den": 4},
            "beats": [
                {
                    "duration": 4, "dotted": False, "status": "normal",
                    "dynamic": "mf", "strumDown": True,
                    "notes": [
                        {"string": 1, "fret": 7, "effect": None},
                        {"string": 2, "fret": 8},
                    ],
                },
                {
                    "duration": 4, "dotted": False, "status": "normal",
                    "dynamic": "f",
                    "notes": [{"string": 1, "fret": 5, "effect": "hammer-on"}],
                },
                {
                    "duration": 4, "dotted": False, "status": "rest",
                    "dynamic": "mf", "notes": [],
                },
                {
                    "duration": 4, "dotted": False, "status": "normal",
                    "dynamic": "mp",
                    "notes": [{"string": 3, "fret": 0, "effect": "ghost"}],
                },
            ],
        }]
    }]
}

REST_SNAPSHOT = {
    "tracks": [{"measures": [{"timeSignature": {"num": 4, "den": 4},
        "beats": [{"duration": 1, "dotted": False, "status": "rest", "notes": []}]}]}]
}


def test_snapshot_to_gp5_creates_file(tmp_path):
    """snapshot_to_gp5가 파일을 생성해야 한다."""
    from app.pipeline.token_to_gp import snapshot_to_gp5

    out = str(tmp_path / "out.gp5")
    result = snapshot_to_gp5(SIMPLE_SNAPSHOT, out)
    assert result == out
    assert (tmp_path / "out.gp5").exists()
    assert (tmp_path / "out.gp5").stat().st_size > 0


def test_snapshot_to_gp5_parseable(tmp_path):
    """생성된 GP5가 guitarpro.parse로 재파싱 가능해야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import snapshot_to_gp5

    out = str(tmp_path / "out.gp5")
    snapshot_to_gp5(SIMPLE_SNAPSHOT, out)
    song = guitarpro.parse(out)
    assert len(song.tracks) >= 1
    assert len(song.tracks[0].measures) == 1


def test_snapshot_to_gp5_note_fret(tmp_path):
    """첫 비트 첫 음표 프렛이 7이어야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import snapshot_to_gp5

    out = str(tmp_path / "out.gp5")
    snapshot_to_gp5(SIMPLE_SNAPSHOT, out)
    song = guitarpro.parse(out)
    beat = song.tracks[0].measures[0].voices[0].beats[0]
    frets = {n.value for n in beat.notes}
    assert 7 in frets
    assert 8 in frets


def test_snapshot_to_gp5_rest(tmp_path):
    """쉼표 스냅샷도 정상 변환돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import snapshot_to_gp5

    out = str(tmp_path / "out.gp5")
    snapshot_to_gp5(REST_SNAPSHOT, out)
    song = guitarpro.parse(out)
    assert song is not None


def test_snapshot_to_gp5_no_string_reversal(tmp_path):
    """GP 컨벤션 스트링 번호 — 반전 없이 그대로 저장돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import snapshot_to_gp5

    snap = {"tracks": [{"measures": [{"timeSignature": {"num": 4, "den": 4},
        "beats": [{"duration": 4, "dotted": False, "status": "normal",
                   "dynamic": "mf",
                   "notes": [{"string": 1, "fret": 5}]}]}]}]}
    out = str(tmp_path / "out.gp5")
    snapshot_to_gp5(snap, out)
    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert note.string == 1


def test_snapshot_to_gp5_empty_raises(tmp_path):
    """트랙 없으면 ValueError가 발생해야 한다."""
    from app.pipeline.token_to_gp import snapshot_to_gp5

    with pytest.raises(ValueError, match="트랙"):
        snapshot_to_gp5({"tracks": []}, str(tmp_path / "out.gp5"))
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
pytest tests/test_token_to_gp.py::test_snapshot_to_gp5_creates_file -v
```

예상: `ImportError: cannot import name 'snapshot_to_gp5'`

- [ ] **Step 3: snapshot_to_gp5() 구현**

`app/pipeline/token_to_gp.py` 파일 끝 `token_texts_to_gp5` 다음에 추가:

```python
def snapshot_to_gp5(snapshot: dict, out_path: str) -> str:
    """ScoreSnapshot JSON dict → .gp5 파일 저장.

    ScoreSnapshot 스트링 번호는 GP 컨벤션(1=high E)을 따르므로 반전 없음.

    Raises
    ------
    ValueError
        트랙 또는 마디 없는 경우.
    """
    _DYN_STR_MAP = {"ppp": 15, "pp": 31, "p": 47, "mp": 63,
                    "mf": 79, "f": 95, "ff": 111, "fff": 127}
    _SLIDE_MAP = {
        "slide-shift": SlideType.shiftSlideTo,
        "slide-legato": SlideType.legatoSlideTo,
        "slide-in-above": SlideType.intoFromAbove,
        "slide-out-below": SlideType.outUpwards,
    }

    tracks_data = snapshot.get("tracks", [])
    if not tracks_data:
        raise ValueError("snapshot에 트랙 없음")
    measures_data = tracks_data[0].get("measures", [])
    if not measures_data:
        raise ValueError("snapshot에 마디 없음")

    song = gpm.Song()
    track = song.tracks[0]
    track.name = "Guitar"

    def _fill_snap(measure: gpm.Measure, mdata: dict) -> None:
        voice = measure.voices[0]
        voice.beats = []
        ts = mdata.get("timeSignature", {})
        expected = (ts.get("num", 4) / ts.get("den", 4)) * 64
        accumulated = 0.0

        for bdata in mdata.get("beats", []):
            dur_val = bdata.get("duration", 4)
            is_dotted = bdata.get("dotted", False)
            base = _DUR_UNITS.get(dur_val, 16)
            units = base * 1.5 if is_dotted else float(base)
            if accumulated + units > expected + 0.01:
                logger.warning("snapshot 마디 초과 비트 제거: dur=%s", dur_val)
                break
            accumulated += units

            beat = Beat(voice)
            beat.duration = gpm.Duration()
            beat.duration.value = dur_val
            if is_dotted:
                beat.duration.isDotted = True

            notes_data = bdata.get("notes", [])
            if bdata.get("status") == "rest" or not notes_data:
                beat.status = BeatStatus.rest
                beat.notes = []
            else:
                beat.status = BeatStatus.normal
                vel = _DYN_STR_MAP.get(bdata.get("dynamic", "mf"), 95)
                for nd in notes_data:
                    gnote = Note(beat)
                    gnote.string = nd.get("string", 1)
                    gnote.value = nd.get("fret", 0)
                    gnote.velocity = vel
                    eff = nd.get("effect")
                    if eff in ("hammer-on", "pull-off"):
                        gnote.effect.hammer = True
                        gnote.type = NoteType.normal
                    elif eff == "mute":
                        gnote.type = NoteType.dead
                    elif eff == "ghost":
                        gnote.effect.ghostNote = True
                        gnote.type = NoteType.normal
                    elif eff == "harmonic":
                        gnote.effect.harmonic = gpm.NaturalHarmonic()
                        gnote.type = NoteType.normal
                    elif eff in _SLIDE_MAP:
                        gnote.effect.slides = [_SLIDE_MAP[eff]]
                        gnote.type = NoteType.normal
                    else:
                        gnote.type = NoteType.normal
                    beat.notes.append(gnote)

            strum = bdata.get("strumDown")
            if strum is True:
                beat.effect.pickStroke = BeatStrokeDirection.down
                beat.effect.stroke.direction = BeatStrokeDirection.down
                beat.effect.stroke.value = dur_val
            elif strum is False:
                beat.effect.pickStroke = BeatStrokeDirection.up
                beat.effect.stroke.direction = BeatStrokeDirection.up
                beat.effect.stroke.value = dur_val

            voice.beats.append(beat)

        remaining = expected - accumulated
        if remaining > 0.01:
            for dv in _DUR_FILL_ORDER:
                fu = _DUR_UNITS[dv]
                while remaining >= fu - 0.01:
                    rest = Beat(voice)
                    rest.status = BeatStatus.rest
                    rest.duration = gpm.Duration()
                    rest.duration.value = dv
                    rest.notes = []
                    voice.beats.append(rest)
                    remaining -= fu

        if not voice.beats:
            rest = Beat(voice)
            rest.status = BeatStatus.rest
            rest.duration = gpm.Duration()
            rest.duration.value = 4
            rest.notes = []
            voice.beats.append(rest)

    ts0 = measures_data[0].get("timeSignature", {})
    first_mh = song.measureHeaders[0]
    first_mh.number = 1
    first_mh.timeSignature.numerator = ts0.get("num", 4)
    first_mh.timeSignature.denominator.value = ts0.get("den", 4)
    _fill_snap(track.measures[0], measures_data[0])

    start = first_mh.start + first_mh.length
    for i, mdata in enumerate(measures_data[1:], start=2):
        ts = mdata.get("timeSignature", {})
        mh = gpm.MeasureHeader()
        mh.number = i
        mh.start = start
        mh.timeSignature.numerator = ts.get("num", 4)
        mh.timeSignature.denominator.value = ts.get("den", 4)
        song.measureHeaders.append(mh)
        m = gpm.Measure(track, mh)
        _fill_snap(m, mdata)
        track.measures.append(m)
        start += mh.length

    guitarpro.write(song, out_path)
    return out_path
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_token_to_gp.py -v -k "snapshot"
```

예상: 6 passed

- [ ] **Step 5: 전체 기존 테스트도 통과하는지 확인**

```bash
pytest tests/test_token_to_gp.py -v
```

예상: 전체 passed

- [ ] **Step 6: 커밋**

```bash
git add app/pipeline/token_to_gp.py tests/test_token_to_gp.py
git commit -m "feat: token_to_gp - snapshot_to_gp5() ScoreSnapshot → GP5 변환"
```

---

## Task 2: Backend — POST /files/{id}/sync

**Files:**
- Create: `app/routers/edit.py`
- Create: `tests/test_edit.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `snapshot_to_gp5(snapshot, out_path)` (Task 1)
- Produces: `POST /files/{file_id}/sync` → 200 OK / 403 / 404 / 422

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_edit.py` 생성:

```python
import json
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.auth import create_access_token

client = TestClient(app)

VALID_SNAPSHOT = {
    "tracks": [{
        "measures": [{
            "timeSignature": {"num": 4, "den": 4},
            "beats": [
                {"duration": 1, "dotted": False, "status": "rest",
                 "dynamic": "mf", "notes": []}
            ],
        }]
    }]
}


def _make_token(user_id: str) -> str:
    return create_access_token({"sub": user_id, "type": "access"})


def test_sync_200(tmp_path):
    """정상 sync → 200 OK + GP5 파일 덮어씀."""
    from app.database import SessionLocal
    from app.models import User, File

    db = SessionLocal()
    user = User(id="u1", email="a@b.com", provider="google", provider_id="x")
    gp5_path = str(tmp_path / "out.gp5")
    open(gp5_path, "wb").close()
    file = File(id="f1", user_id="u1", name="test", gp5_path=gp5_path)
    db.add(user); db.add(file); db.commit()
    db.close()

    token = _make_token("u1")
    with patch("app.routers.edit.snapshot_to_gp5") as mock_fn:
        mock_fn.return_value = gp5_path
        resp = client.post(
            "/files/f1/sync",
            content=json.dumps(VALID_SNAPSHOT),
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    mock_fn.assert_called_once()


def test_sync_403_wrong_user():
    """타인 파일 접근 → 403."""
    from app.database import SessionLocal
    from app.models import User, File

    db = SessionLocal()
    user2 = User(id="u2", email="b@b.com", provider="google", provider_id="y")
    db.add(user2)
    # f1은 u1 소유 (test_sync_200에서 이미 생성)
    db.commit(); db.close()

    token = _make_token("u2")
    resp = client.post(
        "/files/f1/sync",
        content=json.dumps(VALID_SNAPSHOT),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_sync_404():
    """존재하지 않는 파일 → 404."""
    token = _make_token("u1")
    resp = client.post(
        "/files/nonexistent/sync",
        content=json.dumps(VALID_SNAPSHOT),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    assert resp.status_code == 404


def test_sync_422_bad_json():
    """빈 tracks → 422."""
    token = _make_token("u1")
    resp = client.post(
        "/files/f1/sync",
        content=json.dumps({"tracks": []}),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
pytest tests/test_edit.py::test_sync_200 -v
```

예상: `404 Not Found` (라우터 미등록)

- [ ] **Step 3: edit.py 구현**

`app/routers/edit.py` 생성:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File
from app.pipeline.token_to_gp import snapshot_to_gp5

router = APIRouter(prefix="/files", tags=["edit"])


@router.post("/{file_id}/sync")
def sync_file(
    file_id: str,
    snapshot: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ScoreSnapshot JSON → GP5 재생성 후 저장."""
    f = db.query(File).filter_by(id=file_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.user_id != user.id:
        raise HTTPException(status_code=403, detail="접근 금지")

    try:
        snapshot_to_gp5(snapshot, f.gp5_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}
```

- [ ] **Step 4: main.py에 라우터 등록**

`app/main.py`의 라우터 등록 블록에 추가:

```python
from app.routers.edit import router as edit_router
# ...
app.include_router(edit_router)
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
pytest tests/test_edit.py -v
```

예상: 4 passed

- [ ] **Step 6: 커밋**

```bash
git add app/routers/edit.py tests/test_edit.py app/main.py
git commit -m "feat: edit - POST /files/{id}/sync ScoreSnapshot → GP5 저장"
```

---

## Task 3: Frontend — ScoreSnapshot 타입 + editorStore

**Files:**
- Create: `frontend/src/lib/scoreTypes.ts`
- Create: `frontend/src/store/editorStore.ts`
- Create: `frontend/src/__tests__/editorStore.test.ts`

**Interfaces:**
- Produces:
  - `ScoreSnapshot`, `NotePosition`, `Dynamic`, `Effect` (타입)
  - `useEditorStore` 훅: `selected`, `fileId`, `present`, `saveStatus`, `setSelected`, `setFileId`, `pushSnapshot`, `undo`, `redo`, `setSaveStatus`, `clearHistory`

- [ ] **Step 1: scoreTypes.ts 작성**

`frontend/src/lib/scoreTypes.ts` 생성:

```typescript
export type Effect =
  | 'hammer-on' | 'pull-off'
  | 'slide-shift' | 'slide-legato'
  | 'slide-in-above' | 'slide-out-below'
  | 'mute' | 'ghost' | 'harmonic'

export type Dynamic = 'ppp' | 'pp' | 'p' | 'mp' | 'mf' | 'f' | 'ff' | 'fff'

export interface SnapshotNote {
  string: number      // 1-6, GP 컨벤션 (1=high E)
  fret: number        // 0-24
  effect?: Effect
}

export interface SnapshotBeat {
  duration: 1 | 2 | 4 | 8 | 16 | 32
  dotted: boolean
  status: 'normal' | 'rest'
  notes: SnapshotNote[]
  strumDown?: boolean
  dynamic?: Dynamic
}

export interface SnapshotMeasure {
  timeSignature: { num: number; den: number }
  beats: SnapshotBeat[]
}

export interface ScoreSnapshot {
  tracks: Array<{ measures: SnapshotMeasure[] }>
}

export interface NotePosition {
  trackIndex: number
  measureIndex: number    // 0-based bar index
  voiceIndex: number      // usually 0
  beatIndex: number       // 0-based beat index within voice
  noteIndex: number | null // null = beat selected (no specific note)
}

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'
```

- [ ] **Step 2: 실패 테스트 작성**

`frontend/src/__tests__/editorStore.test.ts` 생성:

```typescript
import { beforeEach, describe, expect, it } from 'vitest'

const SNAP_A: import('../lib/scoreTypes').ScoreSnapshot = {
  tracks: [{ measures: [{ timeSignature: { num: 4, den: 4 }, beats: [] }] }],
}
const SNAP_B: import('../lib/scoreTypes').ScoreSnapshot = {
  tracks: [{ measures: [{ timeSignature: { num: 3, den: 4 }, beats: [] }] }],
}
const SNAP_C: import('../lib/scoreTypes').ScoreSnapshot = {
  tracks: [{ measures: [{ timeSignature: { num: 2, den: 4 }, beats: [] }] }],
}

describe('editorStore', () => {
  beforeEach(() => {
    const { useEditorStore } = require('../store/editorStore')
    useEditorStore.getState().clearHistory()
    useEditorStore.getState().setSelected(null)
  })

  it('pushSnapshot이 present를 업데이트한다', () => {
    const { useEditorStore } = require('../store/editorStore')
    useEditorStore.getState().pushSnapshot(SNAP_A)
    expect(useEditorStore.getState().present).toEqual(SNAP_A)
  })

  it('undo가 이전 스냅샷을 반환한다', () => {
    const { useEditorStore } = require('../store/editorStore')
    useEditorStore.getState().pushSnapshot(SNAP_A)
    useEditorStore.getState().pushSnapshot(SNAP_B)
    const prev = useEditorStore.getState().undo()
    expect(prev).toEqual(SNAP_A)
    expect(useEditorStore.getState().present).toEqual(SNAP_A)
  })

  it('redo가 되돌린 스냅샷을 복원한다', () => {
    const { useEditorStore } = require('../store/editorStore')
    useEditorStore.getState().pushSnapshot(SNAP_A)
    useEditorStore.getState().pushSnapshot(SNAP_B)
    useEditorStore.getState().undo()
    const redone = useEditorStore.getState().redo()
    expect(redone).toEqual(SNAP_B)
    expect(useEditorStore.getState().present).toEqual(SNAP_B)
  })

  it('pushSnapshot이 future를 초기화한다', () => {
    const { useEditorStore } = require('../store/editorStore')
    useEditorStore.getState().pushSnapshot(SNAP_A)
    useEditorStore.getState().pushSnapshot(SNAP_B)
    useEditorStore.getState().undo()
    useEditorStore.getState().pushSnapshot(SNAP_C)
    // redo는 불가 (future 초기화됨)
    const redone = useEditorStore.getState().redo()
    expect(redone).toBeNull()
  })

  it('undo가 불가하면 null 반환', () => {
    const { useEditorStore } = require('../store/editorStore')
    expect(useEditorStore.getState().undo()).toBeNull()
  })

  it('히스토리 최대 100단계', () => {
    const { useEditorStore } = require('../store/editorStore')
    for (let i = 0; i < 105; i++) {
      useEditorStore.getState().pushSnapshot({
        tracks: [{ measures: [{ timeSignature: { num: i, den: 4 }, beats: [] }] }],
      })
    }
    // past는 최대 100개
    expect(useEditorStore.getState()['past'].length).toBeLessThanOrEqual(100)
  })

  it('setSelected와 setFileId가 상태를 업데이트한다', () => {
    const { useEditorStore } = require('../store/editorStore')
    const pos = { trackIndex: 0, measureIndex: 1, voiceIndex: 0, beatIndex: 2, noteIndex: 0 }
    useEditorStore.getState().setSelected(pos)
    useEditorStore.getState().setFileId('file-123')
    expect(useEditorStore.getState().selected).toEqual(pos)
    expect(useEditorStore.getState().fileId).toBe('file-123')
  })
})
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter/frontend
npm test -- --run src/__tests__/editorStore.test.ts 2>&1 | tail -20
```

예상: `Cannot find module '../store/editorStore'`

- [ ] **Step 4: editorStore.ts 구현**

`frontend/src/store/editorStore.ts` 생성:

```typescript
import { create } from 'zustand'
import type { ScoreSnapshot, NotePosition, SaveStatus } from '../lib/scoreTypes'

const MAX_HISTORY = 100

interface EditorState {
  selected: NotePosition | null
  fileId: string | null
  past: ScoreSnapshot[]
  present: ScoreSnapshot | null
  future: ScoreSnapshot[]
  saveStatus: SaveStatus

  setSelected: (pos: NotePosition | null) => void
  setFileId: (id: string | null) => void
  setSaveStatus: (status: SaveStatus) => void
  pushSnapshot: (snap: ScoreSnapshot) => void
  undo: () => ScoreSnapshot | null
  redo: () => ScoreSnapshot | null
  clearHistory: () => void
}

export const useEditorStore = create<EditorState>((set, get) => ({
  selected: null,
  fileId: null,
  past: [],
  present: null,
  future: [],
  saveStatus: 'idle',

  setSelected: (pos) => set({ selected: pos }),
  setFileId: (id) => set({ fileId: id }),
  setSaveStatus: (status) => set({ saveStatus: status }),

  pushSnapshot: (snap) =>
    set((s) => {
      const past = s.present
        ? [...s.past.slice(-(MAX_HISTORY - 1)), s.present]
        : s.past
      return { past, present: snap, future: [] }
    }),

  undo: () => {
    const { past, present, future } = get()
    if (past.length === 0 || present === null) return null
    const prev = past[past.length - 1]
    set({
      past: past.slice(0, -1),
      present: prev,
      future: [present, ...future],
    })
    return prev
  },

  redo: () => {
    const { past, present, future } = get()
    if (future.length === 0 || present === null) return null
    const next = future[0]
    set({
      past: [...past, present],
      present: next,
      future: future.slice(1),
    })
    return next
  },

  clearHistory: () =>
    set({ past: [], present: null, future: [], selected: null, saveStatus: 'idle' }),
}))
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
npm test -- --run src/__tests__/editorStore.test.ts 2>&1 | tail -20
```

예상: 7 passed

- [ ] **Step 6: 커밋**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
git add frontend/src/lib/scoreTypes.ts frontend/src/store/editorStore.ts \
        frontend/src/__tests__/editorStore.test.ts
git commit -m "feat: editorStore - ScoreSnapshot 타입 + 선택 상태 + Undo/Redo 히스토리"
```

---

## Task 4: Frontend — scoreSerializer

**Files:**
- Create: `frontend/src/lib/scoreSerializer.ts`
- Create: `frontend/src/__tests__/scoreSerializer.test.ts`

**Interfaces:**
- Consumes: `ScoreSnapshot`, `Dynamic`, `Effect` (scoreTypes.ts)
- Produces: `serializeScore(score: AlphaTabScore): ScoreSnapshot`
  - `AlphaTabScore` = alphaTab Score 모양의 JS 객체 (런타임 덕 타이핑)

**alphaTab 1.x Score 구조 참고:**
- `score.tracks[i].staves[0].bars[j].voices[k].beats[l]`
- `beat.duration.value: number`, `beat.duration.isDotted: boolean`
- `beat.isRest: boolean`
- `beat.dynamics: number` (0=ppp, 1=pp, 2=p, 3=mp, 4=mf, 5=f, 6=ff, 7=fff)
- `beat.pickStroke: number` (0=None, 1=Up, 2=Down)
- `note.string: number`, `note.fret: number`
- `note.hammerOrPull: boolean`, `note.isGhost: boolean`, `note.isMuted: boolean`
- `note.slideType: number` (SlideType enum), `note.harmonicType: number`

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/scoreSerializer.test.ts` 생성:

```typescript
import { describe, expect, it } from 'vitest'

function makeNote(overrides: Record<string, unknown> = {}) {
  return {
    string: 1, fret: 5,
    hammerOrPull: false, isGhost: false, isMuted: false,
    slideType: 0,  // 0 = None
    harmonicType: 0,  // 0 = None
    ...overrides,
  }
}

function makeBeat(overrides: Record<string, unknown> = {}) {
  return {
    duration: { value: 4, isDotted: false },
    isRest: false,
    dynamics: 4,      // 4 = mf
    pickStroke: 0,    // 0 = None
    notes: [makeNote()],
    ...overrides,
  }
}

function makeScore(beats = [makeBeat()]) {
  return {
    tracks: [{
      staves: [{
        bars: [{
          masterBar: { timeSignatureNumerator: 4, timeSignatureDenominator: 4 },
          voices: [{ beats }],
        }],
      }],
    }],
  }
}

describe('serializeScore', () => {
  it('기본 beat를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore())
    expect(snap.tracks).toHaveLength(1)
    expect(snap.tracks[0].measures).toHaveLength(1)
    const beat = snap.tracks[0].measures[0].beats[0]
    expect(beat.duration).toBe(4)
    expect(beat.dotted).toBe(false)
    expect(beat.status).toBe('normal')
    expect(beat.dynamic).toBe('mf')
    expect(beat.notes[0]).toMatchObject({ string: 1, fret: 5 })
  })

  it('rest beat를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ isRest: true, notes: [] })]))
    expect(snap.tracks[0].measures[0].beats[0].status).toBe('rest')
  })

  it('점음표를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ duration: { value: 4, isDotted: true } })]))
    expect(snap.tracks[0].measures[0].beats[0].dotted).toBe(true)
  })

  it('strumDown=true를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ pickStroke: 2 })]))  // 2 = Down
    expect(snap.tracks[0].measures[0].beats[0].strumDown).toBe(true)
  })

  it('strumUp=false를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ pickStroke: 1 })]))  // 1 = Up
    expect(snap.tracks[0].measures[0].beats[0].strumDown).toBe(false)
  })

  it('hammer-on 이펙트를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ notes: [makeNote({ hammerOrPull: true })] })]))
    expect(snap.tracks[0].measures[0].beats[0].notes[0].effect).toBe('hammer-on')
  })

  it('ghost 이펙트를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ notes: [makeNote({ isGhost: true })] })]))
    expect(snap.tracks[0].measures[0].beats[0].notes[0].effect).toBe('ghost')
  })

  it('mute 이펙트를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ notes: [makeNote({ isMuted: true })] })]))
    expect(snap.tracks[0].measures[0].beats[0].notes[0].effect).toBe('mute')
  })

  it('박자표를 직렬화한다', async () => {
    const score = makeScore()
    score.tracks[0].staves[0].bars[0].masterBar.timeSignatureNumerator = 3
    score.tracks[0].staves[0].bars[0].masterBar.timeSignatureDenominator = 4
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(score)
    expect(snap.tracks[0].measures[0].timeSignature).toEqual({ num: 3, den: 4 })
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter/frontend
npm test -- --run src/__tests__/scoreSerializer.test.ts 2>&1 | tail -20
```

예상: `Cannot find module '../lib/scoreSerializer'`

- [ ] **Step 3: scoreSerializer.ts 구현**

`frontend/src/lib/scoreSerializer.ts` 생성:

```typescript
import type { ScoreSnapshot, SnapshotBeat, SnapshotNote, Dynamic, Effect } from './scoreTypes'

const DYNAMIC_VALUES: Record<number, Dynamic> = {
  0: 'ppp', 1: 'pp', 2: 'p', 3: 'mp', 4: 'mf', 5: 'f', 6: 'ff', 7: 'fff',
}

// alphaTab SlideType 숫자값 → Effect 문자열 (alphaTab 1.x 기준)
const SLIDE_TYPE_MAP: Record<number, Effect> = {
  1: 'slide-shift',
  2: 'slide-legato',
  4: 'slide-in-above',
  8: 'slide-out-below',
}

function getNoteEffect(note: Record<string, unknown>): Effect | undefined {
  if (note.hammerOrPull) return 'hammer-on'
  if (note.isMuted) return 'mute'
  if (note.isGhost) return 'ghost'
  if ((note.harmonicType as number) > 0) return 'harmonic'
  const slideType = note.slideType as number
  if (slideType > 0 && SLIDE_TYPE_MAP[slideType]) return SLIDE_TYPE_MAP[slideType]
  return undefined
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function serializeScore(score: any): ScoreSnapshot {
  const tracks = score.tracks.map((track: any) => {
    const staff = track.staves[0]
    const measures = staff.bars.map((bar: any) => {
      const mb = bar.masterBar
      const voice = bar.voices[0]

      const beats: SnapshotBeat[] = (voice.beats as any[])
        .filter((b: any) => b.duration != null)
        .map((beat: any): SnapshotBeat => {
          const pickStroke = beat.pickStroke as number
          const notes: SnapshotNote[] = (beat.isRest ? [] : (beat.notes as any[])).map(
            (note: any): SnapshotNote => ({
              string: note.string as number,
              fret: note.fret as number,
              effect: getNoteEffect(note),
            }),
          )

          return {
            duration: beat.duration.value as 1 | 2 | 4 | 8 | 16 | 32,
            dotted: beat.duration.isDotted as boolean,
            status: beat.isRest ? 'rest' : 'normal',
            notes,
            dynamic: DYNAMIC_VALUES[beat.dynamics as number] ?? 'mf',
            strumDown: pickStroke === 2 ? true : pickStroke === 1 ? false : undefined,
          }
        })

      return {
        timeSignature: {
          num: mb.timeSignatureNumerator as number,
          den: mb.timeSignatureDenominator as number,
        },
        beats,
      }
    })

    return { measures }
  })

  return { tracks }
}
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
npm test -- --run src/__tests__/scoreSerializer.test.ts 2>&1 | tail -20
```

예상: 9 passed

- [ ] **Step 5: 커밋**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
git add frontend/src/lib/scoreSerializer.ts frontend/src/__tests__/scoreSerializer.test.ts
git commit -m "feat: scoreSerializer - alphaTab Score → ScoreSnapshot 직렬화"
```

---

## Task 5: Frontend — scoreApplier

**Files:**
- Create: `frontend/src/lib/scoreApplier.ts`
- Create: `frontend/src/__tests__/scoreApplier.test.ts`

**Interfaces:**
- Consumes: `NotePosition`, `Effect`, `Dynamic` (scoreTypes.ts)
- Produces:
  - `EditPayload` (union type)
  - `applyEdit(score: any, pos: NotePosition, edit: EditPayload): void` — score를 in-place 수정
  - `applySnapshot(score: any, snap: ScoreSnapshot): void` — Undo/Redo 시 전체 복원

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/scoreApplier.test.ts` 생성:

```typescript
import { describe, expect, it } from 'vitest'
import type { NotePosition } from '../lib/scoreTypes'

function makeNote(overrides: Record<string, unknown> = {}) {
  return { string: 1, fret: 5, hammerOrPull: false, isGhost: false, isMuted: false, slideType: 0, harmonicType: 0, ...overrides }
}

function makeBeat(overrides: Record<string, unknown> = {}) {
  return {
    duration: { value: 4, isDotted: false },
    isRest: false, dynamics: 4, pickStroke: 0,
    notes: [makeNote()],
    ...overrides,
  }
}

function makeScore(beats = [makeBeat()]) {
  return {
    tracks: [{
      staves: [{
        bars: [{
          masterBar: { timeSignatureNumerator: 4, timeSignatureDenominator: 4 },
          voices: [{ beats }],
        }],
      }],
    }],
  }
}

const POS: NotePosition = { trackIndex: 0, measureIndex: 0, voiceIndex: 0, beatIndex: 0, noteIndex: 0 }

describe('applyEdit', () => {
  it('프렛을 변경한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, POS, { type: 'fret', value: 12 })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes[0].fret).toBe(12)
  })

  it('지속시간을 변경한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'duration', value: 8 })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].duration.value).toBe(8)
  })

  it('점음표를 토글한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'dotted', value: true })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].duration.isDotted).toBe(true)
  })

  it('hammer-on 이펙트를 적용한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, POS, { type: 'effect', value: 'hammer-on' })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes[0].hammerOrPull).toBe(true)
  })

  it('이펙트를 null로 초기화한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore([makeBeat({ notes: [makeNote({ hammerOrPull: true })] })])
    applyEdit(score, POS, { type: 'effect', value: null })
    const note = score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes[0]
    expect(note.hammerOrPull).toBe(false)
  })

  it('다이나믹을 변경한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'dynamic', value: 'ff' })
    // 6 = ff
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].dynamics).toBe(6)
  })

  it('strumDown을 설정한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'strumDown', value: true })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].pickStroke).toBe(2)
  })

  it('음표를 추가한다 (string=1, fret=0)', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    const before = score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.length
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'addNote' })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.length).toBe(before + 1)
    const added = score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.at(-1)!
    expect(added).toMatchObject({ string: 1, fret: 0 })
  })

  it('음표를 삭제한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, POS, { type: 'deleteNote' })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.length).toBe(0)
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter/frontend
npm test -- --run src/__tests__/scoreApplier.test.ts 2>&1 | tail -20
```

예상: `Cannot find module '../lib/scoreApplier'`

- [ ] **Step 3: scoreApplier.ts 구현**

`frontend/src/lib/scoreApplier.ts` 생성:

```typescript
import type { NotePosition, Effect, Dynamic, ScoreSnapshot } from './scoreTypes'

export type EditPayload =
  | { type: 'fret'; value: number }
  | { type: 'duration'; value: 1 | 2 | 4 | 8 | 16 | 32 }
  | { type: 'dotted'; value: boolean }
  | { type: 'effect'; value: Effect | null }
  | { type: 'strumDown'; value: boolean | undefined }
  | { type: 'dynamic'; value: Dynamic }
  | { type: 'addNote' }
  | { type: 'deleteNote' }

const DYNAMIC_INDICES: Record<Dynamic, number> = {
  ppp: 0, pp: 1, p: 2, mp: 3, mf: 4, f: 5, ff: 6, fff: 7,
}

// alphaTab SlideType 숫자값 (Effect → 숫자)
const EFFECT_SLIDE_MAP: Partial<Record<Effect, number>> = {
  'slide-shift': 1,
  'slide-legato': 2,
  'slide-in-above': 4,
  'slide-out-below': 8,
}

function getBeat(score: any, pos: NotePosition) {
  return score.tracks[pos.trackIndex]
    .staves[0]
    .bars[pos.measureIndex]
    .voices[pos.voiceIndex]
    .beats[pos.beatIndex]
}

function clearNoteEffects(note: any) {
  note.hammerOrPull = false
  note.isGhost = false
  note.isMuted = false
  note.harmonicType = 0
  note.slideType = 0
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function applyEdit(score: any, pos: NotePosition, edit: EditPayload): void {
  const beat = getBeat(score, pos)

  if (edit.type === 'duration') {
    beat.duration.value = edit.value
  } else if (edit.type === 'dotted') {
    beat.duration.isDotted = edit.value
  } else if (edit.type === 'dynamic') {
    beat.dynamics = DYNAMIC_INDICES[edit.value]
  } else if (edit.type === 'strumDown') {
    beat.pickStroke = edit.value === true ? 2 : edit.value === false ? 1 : 0
  } else if (edit.type === 'addNote') {
    beat.notes.push({ string: 1, fret: 0, hammerOrPull: false, isGhost: false, isMuted: false, slideType: 0, harmonicType: 0 })
    beat.isRest = false
  } else if (edit.type === 'deleteNote' && pos.noteIndex !== null) {
    beat.notes.splice(pos.noteIndex, 1)
    if (beat.notes.length === 0) beat.isRest = true
  } else if (edit.type === 'fret' && pos.noteIndex !== null) {
    beat.notes[pos.noteIndex].fret = edit.value
  } else if (edit.type === 'effect') {
    if (pos.noteIndex === null) return
    const note = beat.notes[pos.noteIndex]
    clearNoteEffects(note)
    if (edit.value === null) return
    if (edit.value === 'hammer-on' || edit.value === 'pull-off') {
      note.hammerOrPull = true
    } else if (edit.value === 'ghost') {
      note.isGhost = true
    } else if (edit.value === 'mute') {
      note.isMuted = true
    } else if (edit.value === 'harmonic') {
      note.harmonicType = 1
    } else if (EFFECT_SLIDE_MAP[edit.value] !== undefined) {
      note.slideType = EFFECT_SLIDE_MAP[edit.value]!
    }
  }
}

// Undo/Redo: 스냅샷 전체를 Score에 반영
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function applySnapshot(score: any, snap: ScoreSnapshot): void {
  const DYNAMIC_INDICES_MAP = DYNAMIC_INDICES
  snap.tracks.forEach((tsnap, ti) => {
    const staff = score.tracks[ti]?.staves[0]
    if (!staff) return
    tsnap.measures.forEach((msnap, mi) => {
      const voice = staff.bars[mi]?.voices[0]
      if (!voice) return
      voice.beats.forEach((beat: any, bi: number) => {
        const bsnap = msnap.beats[bi]
        if (!bsnap) return
        beat.duration.value = bsnap.duration
        beat.duration.isDotted = bsnap.dotted
        beat.isRest = bsnap.status === 'rest'
        beat.dynamics = DYNAMIC_INDICES_MAP[bsnap.dynamic ?? 'mf'] ?? 4
        beat.pickStroke = bsnap.strumDown === true ? 2 : bsnap.strumDown === false ? 1 : 0
        beat.notes = bsnap.notes.map((nsnap) => {
          const note: any = { string: nsnap.string, fret: nsnap.fret, hammerOrPull: false, isGhost: false, isMuted: false, slideType: 0, harmonicType: 0 }
          if (nsnap.effect === 'hammer-on' || nsnap.effect === 'pull-off') note.hammerOrPull = true
          else if (nsnap.effect === 'ghost') note.isGhost = true
          else if (nsnap.effect === 'mute') note.isMuted = true
          else if (nsnap.effect === 'harmonic') note.harmonicType = 1
          else if (nsnap.effect && EFFECT_SLIDE_MAP[nsnap.effect]) note.slideType = EFFECT_SLIDE_MAP[nsnap.effect]!
          return note
        })
      })
    })
  })
}
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
npm test -- --run src/__tests__/scoreApplier.test.ts 2>&1 | tail -20
```

예상: 9 passed

- [ ] **Step 5: 커밋**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
git add frontend/src/lib/scoreApplier.ts frontend/src/__tests__/scoreApplier.test.ts
git commit -m "feat: scoreApplier - alphaTab Score 인플레이스 편집 + 스냅샷 복원"
```

---

## Task 6: Frontend — api.syncFile + useSyncFile 훅

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/useSyncFile.ts`
- Create: `frontend/src/__tests__/useSyncFile.test.ts`

**Interfaces:**
- Consumes: `ScoreSnapshot` (scoreTypes.ts), `SaveStatus` (scoreTypes.ts)
- Produces:
  - `api.syncFile(fileId: string, snapshot: ScoreSnapshot): Promise<void>`
  - `useSyncFile(fileId: string | null, snapshot: ScoreSnapshot | null): void` — 3초 debounce 후 sync, saveStatus 업데이트

- [ ] **Step 1: api.syncFile 추가**

`frontend/src/lib/api.ts`에 추가:

```typescript
// 파일 상단 import에 추가
import type { ScoreSnapshot } from './scoreTypes'

// api 객체에 추가:
  async syncFile(fileId: string, snapshot: ScoreSnapshot): Promise<void> {
    await request<{ ok: boolean }>(`/files/${fileId}/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(snapshot),
    })
  },
```

- [ ] **Step 2: 실패 테스트 작성**

`frontend/src/__tests__/useSyncFile.test.ts` 생성:

```typescript
import { renderHook, act } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'

vi.mock('../lib/api', () => ({
  api: { syncFile: vi.fn().mockResolvedValue(undefined) },
}))
vi.mock('../store/editorStore', () => ({
  useEditorStore: (sel: any) => {
    let _status = 'idle'
    return sel({
      saveStatus: _status,
      setSaveStatus: (s: string) => { _status = s },
    })
  },
}))

import type { ScoreSnapshot } from '../lib/scoreTypes'

const SNAP: ScoreSnapshot = {
  tracks: [{ measures: [{ timeSignature: { num: 4, den: 4 }, beats: [] }] }],
}

describe('useSyncFile', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

  it('3초 후 syncFile을 호출한다', async () => {
    const { api } = await import('../lib/api')
    const { useSyncFile } = await import('../lib/useSyncFile')

    renderHook(() => useSyncFile('file-1', SNAP))
    expect(api.syncFile).not.toHaveBeenCalled()

    await act(async () => { vi.advanceTimersByTime(3000) })
    expect(api.syncFile).toHaveBeenCalledWith('file-1', SNAP)
  })

  it('fileId가 null이면 호출 안 함', async () => {
    const { api } = await import('../lib/api')
    const { useSyncFile } = await import('../lib/useSyncFile')

    renderHook(() => useSyncFile(null, SNAP))
    await act(async () => { vi.advanceTimersByTime(3000) })
    expect(api.syncFile).not.toHaveBeenCalled()
  })

  it('snapshot이 null이면 호출 안 함', async () => {
    const { api } = await import('../lib/api')
    const { useSyncFile } = await import('../lib/useSyncFile')

    renderHook(() => useSyncFile('file-1', null))
    await act(async () => { vi.advanceTimersByTime(3000) })
    expect(api.syncFile).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter/frontend
npm test -- --run src/__tests__/useSyncFile.test.ts 2>&1 | tail -20
```

예상: `Cannot find module '../lib/useSyncFile'`

- [ ] **Step 4: useSyncFile.ts 구현**

`frontend/src/lib/useSyncFile.ts` 생성:

```typescript
import { useEffect, useRef } from 'react'
import { api } from './api'
import { useEditorStore } from '../store/editorStore'
import type { ScoreSnapshot } from './scoreTypes'

export function useSyncFile(fileId: string | null, snapshot: ScoreSnapshot | null): void {
  const setSaveStatus = useEditorStore((s) => s.setSaveStatus)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    if (!fileId || !snapshot) return
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      setSaveStatus('saving')
      try {
        await api.syncFile(fileId, snapshot)
        setSaveStatus('saved')
      } catch {
        setSaveStatus('error')
      }
    }, 3000)

    return () => clearTimeout(timerRef.current)
  }, [fileId, snapshot, setSaveStatus])
}
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
npm test -- --run src/__tests__/useSyncFile.test.ts 2>&1 | tail -20
```

예상: 3 passed

- [ ] **Step 6: 커밋**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
git add frontend/src/lib/api.ts frontend/src/lib/useSyncFile.ts \
        frontend/src/__tests__/useSyncFile.test.ts
git commit -m "feat: api.syncFile + useSyncFile - 3초 debounce 자동저장 훅"
```

---

## Task 7: Frontend — EditPanel 컴포넌트

**Files:**
- Create: `frontend/src/components/Editor/EditPanel.tsx`
- Create: `frontend/src/__tests__/EditPanel.test.tsx`

**Interfaces:**
- Consumes: `NotePosition`, `Effect`, `Dynamic`, `SnapshotBeat`, `SnapshotNote`, `EditPayload` (scoreApplier)
- Produces:
  ```typescript
  interface EditPanelProps {
    selectedPosition: NotePosition | null
    currentBeat: { duration: number; dotted: boolean; status: string; dynamic?: Dynamic; strumDown?: boolean } | null
    currentNote: { string: number; fret: number; effect?: Effect } | null
    onEditBeat: (edit: EditPayload) => void
    onEditNote: (edit: EditPayload) => void
  }
  export default function EditPanel(props: EditPanelProps): JSX.Element
  ```

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/EditPanel.test.tsx` 생성:

```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect } from 'vitest'
import EditPanel from '../components/Editor/EditPanel'
import type { NotePosition } from '../lib/scoreTypes'

const POS: NotePosition = { trackIndex: 0, measureIndex: 0, voiceIndex: 0, beatIndex: 0, noteIndex: 0 }
const BEAT = { duration: 4, dotted: false, status: 'normal', dynamic: 'mf' as const }
const NOTE = { string: 1, fret: 5 }

describe('EditPanel', () => {
  it('선택 없으면 안내 문구를 표시한다', () => {
    render(<EditPanel selectedPosition={null} currentBeat={null} currentNote={null} onEditBeat={vi.fn()} onEditNote={vi.fn()} />)
    expect(screen.getByText(/음표를 클릭/i)).toBeInTheDocument()
  })

  it('프렛 값을 표시한다', () => {
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={NOTE} onEditBeat={vi.fn()} onEditNote={vi.fn()} />)
    const input = screen.getByLabelText(/프렛/i) as HTMLInputElement
    expect(input.value).toBe('5')
  })

  it('프렛 변경 시 onEditNote를 호출한다', async () => {
    const onEditNote = vi.fn()
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={NOTE} onEditBeat={vi.fn()} onEditNote={onEditNote} />)
    const input = screen.getByLabelText(/프렛/i)
    await userEvent.clear(input)
    await userEvent.type(input, '7')
    await userEvent.keyboard('{Enter}')
    expect(onEditNote).toHaveBeenCalledWith({ type: 'fret', value: 7 })
  })

  it('지속시간 버튼 클릭 시 onEditBeat를 호출한다', async () => {
    const onEditBeat = vi.fn()
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={NOTE} onEditBeat={onEditBeat} onEditNote={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: '8' }))
    expect(onEditBeat).toHaveBeenCalledWith({ type: 'duration', value: 8 })
  })

  it('음표 추가 버튼이 존재한다', () => {
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={null} onEditBeat={vi.fn()} onEditNote={vi.fn()} />)
    expect(screen.getByRole('button', { name: /추가|add|\+/i })).toBeInTheDocument()
  })

  it('음표 삭제 버튼 클릭 시 onEditNote를 호출한다', async () => {
    const onEditNote = vi.fn()
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={NOTE} onEditBeat={vi.fn()} onEditNote={onEditNote} />)
    await userEvent.click(screen.getByRole('button', { name: /삭제|delete|×/i }))
    expect(onEditNote).toHaveBeenCalledWith({ type: 'deleteNote' })
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter/frontend
npm test -- --run src/__tests__/EditPanel.test.tsx 2>&1 | tail -20
```

예상: `Cannot find module '../components/Editor/EditPanel'`

- [ ] **Step 3: EditPanel.tsx 구현**

`frontend/src/components/Editor/EditPanel.tsx` 생성:

```typescript
import type { NotePosition, Dynamic, Effect } from '../../lib/scoreTypes'
import type { EditPayload } from '../../lib/scoreApplier'
import { useState } from 'react'

interface Props {
  selectedPosition: NotePosition | null
  currentBeat: {
    duration: number
    dotted: boolean
    status: string
    dynamic?: Dynamic
    strumDown?: boolean
  } | null
  currentNote: { string: number; fret: number; effect?: Effect } | null
  onEditBeat: (edit: EditPayload) => void
  onEditNote: (edit: EditPayload) => void
}

const DURATIONS: Array<1 | 2 | 4 | 8 | 16 | 32> = [1, 2, 4, 8, 16, 32]
const DYNAMICS: Dynamic[] = ['ppp', 'pp', 'p', 'mp', 'mf', 'f', 'ff', 'fff']
const EFFECTS: Array<{ value: Effect; label: string }> = [
  { value: 'hammer-on', label: 'H' },
  { value: 'pull-off', label: 'P' },
  { value: 'slide-shift', label: 'SS' },
  { value: 'slide-legato', label: 'SL' },
  { value: 'slide-in-above', label: 'Si↑' },
  { value: 'slide-out-below', label: 'So↓' },
  { value: 'mute', label: 'X' },
  { value: 'ghost', label: '( )' },
  { value: 'harmonic', label: '⬦' },
]

export default function EditPanel({ selectedPosition, currentBeat, currentNote, onEditBeat, onEditNote }: Props) {
  const [fretInput, setFretInput] = useState<string>(String(currentNote?.fret ?? ''))

  if (!selectedPosition || !currentBeat) {
    return (
      <div style={{ padding: 16, color: '#888', fontSize: 13 }}>
        음표를 클릭하면 편집할 수 있습니다
      </div>
    )
  }

  const handleFretCommit = () => {
    const val = parseInt(fretInput, 10)
    if (!isNaN(val) && val >= 0 && val <= 24) {
      onEditNote({ type: 'fret', value: val })
    }
  }

  return (
    <div style={{ padding: 12, fontSize: 13, display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 지속시간 */}
      <section>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>지속시간</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {DURATIONS.map((d) => (
            <button
              key={d}
              onClick={() => onEditBeat({ type: 'duration', value: d })}
              style={{ fontWeight: currentBeat.duration === d ? 700 : 400 }}
            >
              {d}
            </button>
          ))}
          <button
            onClick={() => onEditBeat({ type: 'dotted', value: !currentBeat.dotted })}
            style={{ fontWeight: currentBeat.dotted ? 700 : 400 }}
          >
            점음표
          </button>
        </div>
      </section>

      {/* 다이나믹 */}
      <section>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>다이나믹</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {DYNAMICS.map((d) => (
            <button
              key={d}
              onClick={() => onEditBeat({ type: 'dynamic', value: d })}
              style={{ fontWeight: currentBeat.dynamic === d ? 700 : 400 }}
            >
              {d}
            </button>
          ))}
        </div>
      </section>

      {/* 스트럼 */}
      <section>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>스트럼</div>
        <div style={{ display: 'flex', gap: 4 }}>
          <button onClick={() => onEditBeat({ type: 'strumDown', value: true })}
            style={{ fontWeight: currentBeat.strumDown === true ? 700 : 400 }}>▼</button>
          <button onClick={() => onEditBeat({ type: 'strumDown', value: false })}
            style={{ fontWeight: currentBeat.strumDown === false ? 700 : 400 }}>▲</button>
          <button onClick={() => onEditBeat({ type: 'strumDown', value: undefined })}>없음</button>
        </div>
      </section>

      {/* 음표 추가 */}
      <section>
        <button onClick={() => onEditBeat({ type: 'addNote' })}>+ 음표 추가</button>
      </section>

      {/* 음표 편집 (음표가 선택된 경우) */}
      {currentNote && selectedPosition.noteIndex !== null && (
        <>
          <hr style={{ margin: '4px 0' }} />

          <section>
            <label htmlFor="fret-input" style={{ fontWeight: 600 }}>프렛</label>
            <input
              id="fret-input"
              type="number"
              min={0}
              max={24}
              value={fretInput !== String(currentNote.fret) ? fretInput : String(currentNote.fret)}
              onChange={(e) => setFretInput(e.target.value)}
              onBlur={handleFretCommit}
              onKeyDown={(e) => { if (e.key === 'Enter') handleFretCommit() }}
              style={{ width: 56, marginLeft: 8 }}
            />
          </section>

          <section>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>이펙트</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              <button
                onClick={() => onEditNote({ type: 'effect', value: null })}
                style={{ fontWeight: !currentNote.effect ? 700 : 400 }}
              >없음</button>
              {EFFECTS.map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => onEditNote({ type: 'effect', value })}
                  style={{ fontWeight: currentNote.effect === value ? 700 : 400 }}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          <section>
            <button onClick={() => onEditNote({ type: 'deleteNote' })}>× 음표 삭제</button>
          </section>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
npm test -- --run src/__tests__/EditPanel.test.tsx 2>&1 | tail -20
```

예상: 6 passed

- [ ] **Step 5: 커밋**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
git add frontend/src/components/Editor/EditPanel.tsx \
        frontend/src/__tests__/EditPanel.test.tsx
git commit -m "feat: EditPanel - 프렛/지속시간/이펙트/다이나믹/스트럼 편집 UI"
```

---

## Task 8: Frontend — ScoreViewer + App.tsx 통합 + 키보드 단축키

**Files:**
- Modify: `frontend/src/components/Editor/ScoreViewer.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/__tests__/ScoreViewer.test.tsx`

**Interfaces:**
- Consumes:
  - `useEditorStore` (editorStore.ts)
  - `serializeScore(score)` (scoreSerializer.ts)
  - `applyEdit(score, pos, edit)`, `applySnapshot(score, snap)`, `EditPayload` (scoreApplier.ts)
  - `useSyncFile(fileId, snapshot)` (useSyncFile.ts)
  - `EditPanel` (EditPanel.tsx)
- Produces: 완성된 3컬럼 편집 UI

- [ ] **Step 1: ScoreViewer.tsx 전체 교체**

`frontend/src/components/Editor/ScoreViewer.tsx`:

```typescript
import { useEffect, useRef, useState, useCallback } from 'react'
import { initAlphaTab } from '../../lib/alphatab'
import type * as alphaTab from '@coderline/alphatab'
import { useEditorStore } from '../../store/editorStore'
import { serializeScore } from '../../lib/scoreSerializer'
import { applyEdit, applySnapshot, type EditPayload } from '../../lib/scoreApplier'
import { useSyncFile } from '../../lib/useSyncFile'
import EditPanel from './EditPanel'
import type { NotePosition, Dynamic, Effect } from '../../lib/scoreTypes'

interface Props {
  gp5Buffer: ArrayBuffer | null
}

export default function ScoreViewer({ gp5Buffer }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const apiRef = useRef<alphaTab.AlphaTabApi | null>(null)
  const [playing, setPlaying] = useState(false)
  const [loaded, setLoaded] = useState(false)

  const { selected, fileId, present, saveStatus, setSelected, pushSnapshot, undo, redo } = useEditorStore()

  // 현재 선택된 beat/note 정보 추출
  const currentBeat = (() => {
    if (!selected || !apiRef.current?.score) return null
    const api = apiRef.current
    try {
      const beat = (api.score as any).tracks[selected.trackIndex]
        ?.staves[0]?.bars[selected.measureIndex]
        ?.voices[selected.voiceIndex]?.beats[selected.beatIndex]
      if (!beat) return null
      const DYNAMIC_VALUES: Record<number, Dynamic> = { 0:'ppp',1:'pp',2:'p',3:'mp',4:'mf',5:'f',6:'ff',7:'fff' }
      return {
        duration: beat.duration.value,
        dotted: beat.duration.isDotted,
        status: beat.isRest ? 'rest' : 'normal',
        dynamic: DYNAMIC_VALUES[beat.dynamics] ?? 'mf',
        strumDown: beat.pickStroke === 2 ? true : beat.pickStroke === 1 ? false : undefined,
      }
    } catch { return null }
  })()

  const currentNote = (() => {
    if (!selected || selected.noteIndex === null || !apiRef.current?.score) return null
    try {
      const beat = (apiRef.current.score as any).tracks[selected.trackIndex]
        ?.staves[0]?.bars[selected.measureIndex]
        ?.voices[selected.voiceIndex]?.beats[selected.beatIndex]
      const note = beat?.notes[selected.noteIndex]
      if (!note) return null
      const EFFECT_MAP: Record<number, Effect> = { 1:'slide-shift',2:'slide-legato',4:'slide-in-above',8:'slide-out-below' }
      let effect: Effect | undefined
      if (note.hammerOrPull) effect = 'hammer-on'
      else if (note.isMuted) effect = 'mute'
      else if (note.isGhost) effect = 'ghost'
      else if (note.harmonicType > 0) effect = 'harmonic'
      else if (note.slideType > 0) effect = EFFECT_MAP[note.slideType]
      return { string: note.string, fret: note.fret, effect }
    } catch { return null }
  })()

  const commitEdit = useCallback((edit: EditPayload) => {
    if (!apiRef.current?.score || !selected) return
    applyEdit(apiRef.current.score, selected, edit)
    const snap = serializeScore(apiRef.current.score)
    pushSnapshot(snap)
    apiRef.current.render()
  }, [selected, pushSnapshot])

  // 자동저장
  useSyncFile(fileId, present)

  // alphaTab 초기화
  useEffect(() => {
    if (!containerRef.current) return
    const api = initAlphaTab(containerRef.current)
    apiRef.current = api

    api.scoreLoaded.on(() => setLoaded(true))
    api.playerStateChanged.on((e: any) => setPlaying(e.state === 1))
    api.noteMouseDown.on((note: any) => {
      const pos: NotePosition = {
        trackIndex: 0,
        measureIndex: note.beat.voice.bar.index as number,
        voiceIndex: note.beat.voice.index as number,
        beatIndex: note.beat.index as number,
        noteIndex: note.index as number,
      }
      setSelected(pos)
    })

    return () => { api.destroy(); apiRef.current = null }
  }, [setSelected])

  // GP5 로드
  useEffect(() => {
    if (!apiRef.current || !gp5Buffer) return
    setLoaded(false)
    setSelected(null)
    apiRef.current.load(gp5Buffer)
  }, [gp5Buffer, setSelected])

  // 키보드 단축키
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && !e.shiftKey && e.key === 'z') {
        e.preventDefault()
        const prev = undo()
        if (prev && apiRef.current?.score) {
          applySnapshot(apiRef.current.score, prev)
          apiRef.current.render()
        }
      } else if (mod && (e.shiftKey && e.key === 'z' || e.key === 'y')) {
        e.preventDefault()
        const next = redo()
        if (next && apiRef.current?.score) {
          applySnapshot(apiRef.current.score, next)
          apiRef.current.render()
        }
      } else if (e.key === 'Delete' && selected) {
        commitEdit({ type: 'deleteNote' })
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [undo, redo, selected, commitEdit])

  if (!gp5Buffer) {
    return (
      <div style={{ padding: 32, textAlign: 'center', color: '#666' }}>
        악보를 불러오세요 — PDF를 업로드하거나 파일 목록에서 선택하세요
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      {/* 악보 영역 */}
      <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '8px 0', display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={() => apiRef.current?.playPause()} disabled={!loaded}>
            {playing ? '일시정지' : '재생'}
          </button>
          <span style={{ fontSize: 12, color: '#888', marginLeft: 8 }}>
            {saveStatus === 'saving' ? '저장 중…'
              : saveStatus === 'saved' ? '저장됨'
              : saveStatus === 'error' ? '저장 실패'
              : ''}
          </span>
        </div>
        <div ref={containerRef} style={{ width: '100%', flex: 1 }} />
      </div>

      {/* EditPanel */}
      <div style={{ width: 280, borderLeft: '1px solid #ddd', overflowY: 'auto', flexShrink: 0 }}>
        <EditPanel
          selectedPosition={selected}
          currentBeat={currentBeat}
          currentNote={currentNote}
          onEditBeat={commitEdit}
          onEditNote={commitEdit}
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: App.tsx — ScoreViewer에 fileId 전달하도록 수정**

`frontend/src/App.tsx`의 `MainPage` 컴포넌트 수정:

```typescript
import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import { useEditorStore } from './store/editorStore'
import LoginPage from './components/Auth/LoginPage'
import OAuthCallback from './components/Auth/OAuthCallback'
import ScoreViewer from './components/Editor/ScoreViewer'
import UploadButton from './components/FileManager/UploadButton'
import FileList from './components/FileManager/FileList'

function MainPage() {
  const [gp5Buffer, setGp5Buffer] = useState<ArrayBuffer | null>(null)
  const { token, logout } = useAuthStore()
  const { setFileId, clearHistory } = useEditorStore()

  const handleComplete = (jobId: string, buf: ArrayBuffer, fileId?: string | null) => {
    clearHistory()
    setGp5Buffer(buf)
    setFileId(fileId ?? null)
  }

  const handleFileSelect = (buf: ArrayBuffer, fileId: string) => {
    clearHistory()
    setGp5Buffer(buf)
    setFileId(fileId)
  }

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      {/* 사이드바 */}
      <aside style={{ width: 260, minWidth: 200, borderRight: '1px solid #ddd', padding: 16, overflowY: 'auto', flexShrink: 0 }}>
        <h2 style={{ marginTop: 0 }}>GP Converter</h2>
        <UploadButton onComplete={handleComplete} />
        <hr />
        <h3>내 파일</h3>
        {token ? (
          <FileList onSelect={handleFileSelect} />
        ) : (
          <p style={{ fontSize: 13, color: '#666' }}>로그인하면 파일이 저장됩니다</p>
        )}
        {token && (
          <button onClick={logout} style={{ marginTop: 16, fontSize: 12 }}>로그아웃</button>
        )}
      </aside>

      {/* 메인 편집 영역 */}
      <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <ScoreViewer gp5Buffer={gp5Buffer} />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/auth/callback" element={<OAuthCallback />} />
        <Route path="/" element={<MainPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
```

**주의:** `UploadButton`의 `onComplete` 시그니처를 확인하고, `fileId`를 3번째 인자로 전달하도록 수정이 필요할 수 있음. 기존 `onComplete: (jobId: string, buf: ArrayBuffer) => void`에 `fileId?: string | null`을 추가:

`frontend/src/components/FileManager/UploadButton.tsx` — props 타입 수정:
```typescript
// 기존
onComplete: (jobId: string, buf: ArrayBuffer) => void
// 변경
onComplete: (jobId: string, buf: ArrayBuffer, fileId?: string | null) => void
```

`UploadButton` 내부에서 `fileId`를 `/convert` 응답에서 받아 `onComplete(jobId, buf, fileId)` 전달.

`frontend/src/components/FileManager/FileList.tsx` — `onSelect` 시그니처 확인:
- 현재 `onSelect: (buf: ArrayBuffer) => void` → `onSelect: (buf: ArrayBuffer, fileId: string) => void` 로 수정, 클릭 시 `file.id` 전달.

- [ ] **Step 3: ScoreViewer 테스트 업데이트**

`frontend/src/__tests__/ScoreViewer.test.tsx` — noteMouseDown mock 추가:

```typescript
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

vi.mock('../lib/alphatab', () => ({
  initAlphaTab: vi.fn().mockReturnValue({
    scoreLoaded: { on: vi.fn() },
    playerStateChanged: { on: vi.fn() },
    noteMouseDown: { on: vi.fn() },
    load: vi.fn(),
    playPause: vi.fn(),
    destroy: vi.fn(),
    render: vi.fn(),
    score: null,
  }),
}))
vi.mock('../store/editorStore', () => ({
  useEditorStore: vi.fn().mockReturnValue({
    selected: null, fileId: null, present: null, saveStatus: 'idle',
    setSelected: vi.fn(), pushSnapshot: vi.fn(), undo: vi.fn(), redo: vi.fn(),
    clearHistory: vi.fn(),
  }),
}))
vi.mock('../lib/useSyncFile', () => ({ useSyncFile: vi.fn() }))

import ScoreViewer from '../components/Editor/ScoreViewer'

test('gp5Buffer 없으면 안내 문구 표시', () => {
  render(<ScoreViewer gp5Buffer={null} />)
  expect(screen.getByText(/악보를 불러오세요/i)).toBeInTheDocument()
})

test('gp5Buffer 있으면 재생 버튼 표시', () => {
  render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)
  expect(screen.getByRole('button', { name: /재생/i })).toBeInTheDocument()
})
```

- [ ] **Step 4: 전체 프론트엔드 테스트 통과 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter/frontend
npm test -- --run 2>&1 | tail -30
```

예상: 전체 passed (기존 테스트 포함)

- [ ] **Step 5: TypeScript 빌드 오류 확인**

```bash
npx tsc --noEmit 2>&1 | head -40
```

예상: 오류 없음 (또는 수정)

- [ ] **Step 6: 전체 백엔드 테스트 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
pytest --ignore=tests/test_integration.py -v 2>&1 | tail -20
```

예상: 전체 passed

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/components/Editor/ScoreViewer.tsx \
        frontend/src/components/Editor/EditPanel.tsx \
        frontend/src/components/FileManager/UploadButton.tsx \
        frontend/src/components/FileManager/FileList.tsx \
        frontend/src/App.tsx \
        frontend/src/__tests__/ScoreViewer.test.tsx
git commit -m "feat: ScoreViewer + App - noteMouseDown 연결, EditPanel 통합, 3컬럼 레이아웃, 키보드 단축키"
```
