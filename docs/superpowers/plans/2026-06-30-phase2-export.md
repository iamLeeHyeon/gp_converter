# Phase 2 내보내기 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GP5 다운로드, PDF 인쇄, MIDI 내보내기 세 가지 export 기능 추가

**Architecture:** GP5는 서버에 이미 존재하는 파일을 FileResponse로 반환. PDF는 클라이언트에서 `alphaTab.print()` 호출로 브라우저 인쇄 다이얼로그 열기. MIDI는 서버에서 guitarpro+mido로 GP5→MIDI 변환 후 FileResponse. MP3/WAV는 이 플랜 범위 외 (alphaSynth 오디오 녹화 필요).

**Tech Stack:** FastAPI FileResponse, guitarpro 0.10.x, mido ≥ 1.3, React + vitest

## Global Constraints

- alphaTab 버전: `^1.8.3`. print API 시그니처: `api.print(width?: string, additionalSettings?: unknown): void`
- PyGuitarPro 모듈명: `guitarpro` (import as `import guitarpro as gpm`)
- mido: `>=1.3` — 신규 의존성, `requirements.txt`에 추가 필수
- 모든 내보내기 엔드포인트: Bearer 인증 필수 (`get_current_user` dependency)
- 403: 타인 파일, 404: 파일 없음 또는 GP5 파일 경로 없음, 422: MIDI 변환 실패
- 백엔드 테스트: pytest + TestClient, `SessionLocal()` 직접 사용 (test_edit.py 패턴), DB override 없음
- 프론트 테스트: vitest + @testing-library/react + userEvent (EditPanel.test.tsx 패턴)

---

### Task 1: GP5 다운로드 엔드포인트

**Files:**
- Create: `app/routers/export.py`
- Modify: `app/main.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `app.models.File` (`.gp5_path`, `.user_id`, `.name`), `app.dependencies.get_current_user`
- Produces: `GET /files/{file_id}/download` → `FileResponse(media_type="application/octet-stream", filename=f"{file.name}.gp5")`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_export.py
import os, json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.auth import create_access_token

client = TestClient(app)


def _tok(uid: str) -> str:
    return create_access_token(uid)


def _setup_user_file(db, tmp_path, uid="u1", fid="f1", gp5_bytes=b"GP5DATA"):
    from app.models import User, File
    path = str(tmp_path / f"{fid}.gp5")
    with open(path, "wb") as f:
        f.write(gp5_bytes)
    user = User(id=uid, email=f"{uid}@x.com", provider="google", provider_id=uid)
    file = File(id=fid, user_id=uid, name="my_song", gp5_path=path)
    db.merge(user); db.merge(file); db.commit()
    return path


# ── Task 1 ──────────────────────────────────────────────────────────────────

class TestGP5Download:
    def test_200_returns_gp5_file(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        path = _setup_user_file(db, tmp_path)
        db.close()

        resp = client.get("/files/f1/download",
                          headers={"Authorization": f"Bearer {_tok('u1')}"})
        assert resp.status_code == 200
        assert resp.content == b"GP5DATA"
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_403_wrong_user(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User
        db = SessionLocal()
        _setup_user_file(db, tmp_path, uid="u1", fid="f1")
        db.merge(User(id="u2", email="u2@x.com", provider="google", provider_id="u2"))
        db.commit(); db.close()

        resp = client.get("/files/f1/download",
                          headers={"Authorization": f"Bearer {_tok('u2')}"})
        assert resp.status_code == 403

    def test_404_file_not_found(self):
        resp = client.get("/files/nonexistent/download",
                          headers={"Authorization": f"Bearer {_tok('u1')}"})
        assert resp.status_code == 404

    def test_404_gp5_path_missing_on_disk(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User, File
        db = SessionLocal()
        db.merge(User(id="u3", email="u3@x.com", provider="google", provider_id="u3"))
        db.merge(File(id="f3", user_id="u3", name="gone", gp5_path="/nonexistent/path.gp5"))
        db.commit(); db.close()

        resp = client.get("/files/f3/download",
                          headers={"Authorization": f"Bearer {_tok('u3')}"})
        assert resp.status_code == 404
```

- [ ] **Step 2: 테스트 실패 확인**

```
pytest tests/test_export.py -v -k "TestGP5Download"
```

Expected: 4× FAIL (404 "Not Found" from unregistered router)

- [ ] **Step 3: `app/routers/export.py` 구현**

```python
# app/routers/export.py
import os
import tempfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File

router = APIRouter(prefix="/files", tags=["export"])


@router.get("/{file_id}/download")
def download_gp5(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GP5 파일 다운로드."""
    f = db.query(File).filter_by(id=file_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.user_id != user.id:
        raise HTTPException(status_code=403, detail="접근 금지")
    if not f.gp5_path or not os.path.exists(f.gp5_path):
        raise HTTPException(status_code=404, detail="GP5 파일 없음")
    return FileResponse(
        f.gp5_path,
        media_type="application/octet-stream",
        filename=f"{f.name}.gp5",
    )
```

- [ ] **Step 4: `app/main.py`에 export_router 등록**

`app/main.py` 상단 import 블록에 추가:
```python
from app.routers.export import router as export_router
```

`app.include_router(edit_router)` 다음 줄에 추가:
```python
app.include_router(export_router)
```

- [ ] **Step 5: 테스트 통과 확인**

```
pytest tests/test_export.py -v -k "TestGP5Download"
```

Expected: 4× PASS

- [ ] **Step 6: 커밋**

```bash
git add app/routers/export.py app/main.py tests/test_export.py
git commit -m "feat: GET /files/{id}/download — GP5 파일 다운로드 엔드포인트"
```

---

### Task 2: MIDI 변환 백엔드

**Files:**
- Create: `app/pipeline/midi_export.py`
- Modify: `app/routers/export.py`, `requirements.txt`
- Test: `tests/test_export.py` (TestMidiExport 클래스 추가)

**Interfaces:**
- Consumes: `guitarpro.parse(path)` → `Song`, `mido.MidiFile`, `gpm.BeatStatus`, `gpm.NoteType`
- Produces: `gp5_to_midi(gp5_path: str, out_path: str) -> str` (out_path 반환)

- [ ] **Step 1: requirements.txt에 mido 추가**

`requirements.txt` 끝에 한 줄 추가:
```
mido>=1.3
```

설치:
```
pip install "mido>=1.3"
```

- [ ] **Step 2: 실패하는 단위 테스트 작성**

`tests/test_export.py`에 아래 클래스 추가:

```python
# tests/test_export.py (TestMidiExport 클래스 추가)
import mido

class TestMidiExport:
    def test_gp5_to_midi_produces_valid_midi(self, tmp_path):
        """실제 GP5 → MIDI 변환 후 mido로 파싱 가능 여부 확인."""
        from app.pipeline.token_to_gp import snapshot_to_gp5
        from app.pipeline.midi_export import gp5_to_midi

        gp5_path = str(tmp_path / "test.gp5")
        snapshot_to_gp5({
            "tracks": [{
                "measures": [{
                    "timeSignature": {"num": 4, "den": 4},
                    "beats": [
                        {"duration": 4, "dotted": False, "status": "normal",
                         "dynamic": "mf", "notes": [{"string": 1, "fret": 5}]},
                        {"duration": 4, "dotted": False, "status": "rest",
                         "dynamic": "mf", "notes": []},
                    ],
                }]
            }]
        }, gp5_path)

        midi_path = str(tmp_path / "out.mid")
        result = gp5_to_midi(gp5_path, midi_path)

        assert result == midi_path
        assert os.path.exists(midi_path)
        mid = mido.MidiFile(midi_path)
        assert mid.ticks_per_beat == 960
        # 템포 트랙 포함 최소 2개 트랙
        assert len(mid.tracks) >= 2
        # 음표가 있는 트랙에 note_on 메시지 존재
        note_ons = [m for t in mid.tracks for m in t if m.type == 'note_on' and m.velocity > 0]
        assert len(note_ons) >= 1

    def test_gp5_to_midi_correct_pitch(self, tmp_path):
        """현 1, 프렛 5 → MIDI pitch 69 (E4 string open=64, +5=69)."""
        from app.pipeline.token_to_gp import snapshot_to_gp5
        from app.pipeline.midi_export import gp5_to_midi

        gp5_path = str(tmp_path / "pitch.gp5")
        snapshot_to_gp5({
            "tracks": [{
                "measures": [{
                    "timeSignature": {"num": 4, "den": 4},
                    "beats": [
                        {"duration": 4, "dotted": False, "status": "normal",
                         "dynamic": "mf", "notes": [{"string": 1, "fret": 5}]},
                    ],
                }]
            }]
        }, gp5_path)

        midi_path = str(tmp_path / "pitch.mid")
        gp5_to_midi(gp5_path, midi_path)
        mid = mido.MidiFile(midi_path)
        note_ons = [m for t in mid.tracks for m in t if m.type == 'note_on' and m.velocity > 0]
        assert any(m.note == 69 for m in note_ons)

    def test_midi_endpoint_200(self, tmp_path):
        """MIDI 엔드포인트 — 200 + audio/midi Content-Type."""
        from app.database import SessionLocal
        with patch("app.routers.export.gp5_to_midi") as mock_fn:
            midi_out = str(tmp_path / "mock.mid")
            open(midi_out, "wb").write(b"MThd")  # 최소 MIDI 헤더
            mock_fn.return_value = midi_out

            db = SessionLocal()
            _setup_user_file(db, tmp_path, uid="u4", fid="f4")
            db.close()

            resp = client.get("/files/f4/export/midi",
                              headers={"Authorization": f"Bearer {_tok('u4')}"})
        assert resp.status_code == 200
        assert "midi" in resp.headers.get("content-type", "")

    def test_midi_endpoint_403(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User
        db = SessionLocal()
        _setup_user_file(db, tmp_path, uid="u5", fid="f5")
        db.merge(User(id="u6", email="u6@x.com", provider="google", provider_id="u6"))
        db.commit(); db.close()

        resp = client.get("/files/f5/export/midi",
                          headers={"Authorization": f"Bearer {_tok('u6')}"})
        assert resp.status_code == 403
```

- [ ] **Step 3: 테스트 실패 확인**

```
pytest tests/test_export.py::TestMidiExport -v
```

Expected: FAIL (ModuleNotFoundError: midi_export)

- [ ] **Step 4: `app/pipeline/midi_export.py` 구현**

```python
# app/pipeline/midi_export.py
"""GP5 파일 → MIDI 변환 (guitarpro + mido)."""
import os
import tempfile

import guitarpro as gpm
import mido


def gp5_to_midi(gp5_path: str, out_path: str) -> str:
    """GP5 파일을 MIDI로 변환해 out_path에 저장한다. out_path를 반환."""
    song = gpm.parse(gp5_path)
    ticks_per_beat = 960
    mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)

    # 트랙 0: 템포
    t0 = mido.MidiTrack()
    tempo_us = int(60_000_000 / max(song.tempo, 1))
    t0.append(mido.MetaMessage('set_tempo', tempo=tempo_us, time=0))
    mid.tracks.append(t0)

    for ti, track in enumerate(song.tracks):
        # (절대 tick, 메시지 타입, pitch, velocity) 이벤트 수집
        events: list[tuple[int, str, int, int]] = []
        abs_tick = 0

        for measure in track.measures:
            for voice in measure.voices:
                for beat in voice.beats:
                    dur = beat.duration.time  # ticks (quarter=960)
                    if beat.status == gpm.BeatStatus.normal:
                        for note in beat.notes:
                            if note.type == gpm.NoteType.normal:
                                open_val = track.strings[note.string - 1].value
                                pitch = min(127, max(0, open_val + note.value))
                                events.append((abs_tick, 'note_on', pitch, 80))
                                events.append((abs_tick + dur, 'note_off', pitch, 0))
                    abs_tick += dur

        # 같은 tick에서 note_off를 note_on보다 먼저 처리
        events.sort(key=lambda e: (e[0], 0 if e[1] == 'note_off' else 1))

        # 절대 tick → delta tick 변환
        midi_track = mido.MidiTrack()
        ch = min(ti, 15)
        prev = 0
        for t_abs, msg_type, pitch, vel in events:
            delta = t_abs - prev
            midi_track.append(
                mido.Message(msg_type, channel=ch, note=pitch, velocity=vel, time=delta)
            )
            prev = t_abs
        mid.tracks.append(midi_track)

    mid.save(out_path)
    return out_path
```

- [ ] **Step 5: `app/routers/export.py`에 MIDI 엔드포인트 추가**

파일 상단에 import 추가:
```python
from app.pipeline.midi_export import gp5_to_midi
```

`download_gp5` 함수 다음에 추가:

```python
@router.get("/{file_id}/export/midi")
def export_midi(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GP5 → MIDI 변환 후 다운로드."""
    f = db.query(File).filter_by(id=file_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.user_id != user.id:
        raise HTTPException(status_code=403, detail="접근 금지")
    if not f.gp5_path or not os.path.exists(f.gp5_path):
        raise HTTPException(status_code=404, detail="GP5 파일 없음")

    try:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mid")
        os.close(tmp_fd)
        gp5_to_midi(f.gp5_path, tmp_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"MIDI 변환 실패: {e}")

    return FileResponse(
        tmp_path,
        media_type="audio/midi",
        filename=f"{f.name}.mid",
        background=None,  # FileResponse가 전송 후 파일 삭제하지 않음 (tmp는 OS가 정리)
    )
```

- [ ] **Step 6: 전체 테스트 통과 확인**

```
pytest tests/test_export.py -v
```

Expected: 모두 PASS

- [ ] **Step 7: 커밋**

```bash
git add app/pipeline/midi_export.py app/routers/export.py requirements.txt tests/test_export.py
git commit -m "feat: MIDI 내보내기 — gp5_to_midi() + GET /files/{id}/export/midi"
```

---

### Task 3: ExportMenu UI + api.ts 다운로드 함수 + ScoreViewer 통합

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/Editor/ExportMenu.tsx`
- Modify: `frontend/src/components/Editor/ScoreViewer.tsx`
- Test: `frontend/src/__tests__/api.download.test.ts`
- Test: `frontend/src/__tests__/ExportMenu.test.tsx`

**Interfaces:**
- Consumes: `GET /files/{id}/download`, `GET /files/{id}/export/midi`, `AlphaTabApi.print()`
- Produces:
  - `api.downloadGP5(fileId: string, filename: string): Promise<void>`
  - `api.downloadMIDI(fileId: string, filename: string): Promise<void>`
  - `<ExportMenu fileId={string|null} onPrint={() => void} />` 컴포넌트

- [ ] **Step 1: api.ts 다운로드 테스트 작성**

새 파일 `frontend/src/__tests__/api.download.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

// URL.createObjectURL / revokeObjectURL 모킹
const mockCreateURL = vi.fn(() => 'blob:mock-url')
const mockRevokeURL = vi.fn()
vi.stubGlobal('URL', { createObjectURL: mockCreateURL, revokeObjectURL: mockRevokeURL })

// anchor click 모킹
let lastAnchor: { href: string; download: string; click: ReturnType<typeof vi.fn> } | null = null
vi.spyOn(document, 'createElement').mockImplementation((tag) => {
  if (tag === 'a') {
    lastAnchor = { href: '', download: '', click: vi.fn() }
    return lastAnchor as any
  }
  return document.createElement(tag)
})

beforeEach(() => {
  mockFetch.mockReset()
  mockCreateURL.mockClear()
  lastAnchor = null
})

describe('api.downloadGP5', () => {
  it('GET /files/:id/download 호출 후 blob 다운로드 트리거', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      blob: async () => new Blob(['GP5DATA']),
    })
    const { api } = await import('../lib/api')
    await api.downloadGP5('f1', 'my_song.gp5')

    expect(mockFetch).toHaveBeenCalledWith(
      '/files/f1/download',
      expect.objectContaining({ headers: expect.any(Object) })
    )
    expect(lastAnchor?.download).toBe('my_song.gp5')
    expect(lastAnchor?.click).toHaveBeenCalled()
    expect(mockRevokeURL).toHaveBeenCalledWith('blob:mock-url')
  })

  it('서버 오류 시 Error throw', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: '파일 없음' }),
    })
    const { api } = await import('../lib/api')
    await expect(api.downloadGP5('bad', 'x.gp5')).rejects.toThrow('파일 없음')
  })
})

describe('api.downloadMIDI', () => {
  it('GET /files/:id/export/midi 호출 후 blob 다운로드 트리거', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      blob: async () => new Blob(['MThd']),
    })
    const { api } = await import('../lib/api')
    await api.downloadMIDI('f1', 'my_song.mid')

    expect(mockFetch).toHaveBeenCalledWith(
      '/files/f1/export/midi',
      expect.objectContaining({ headers: expect.any(Object) })
    )
    expect(lastAnchor?.download).toBe('my_song.mid')
    expect(lastAnchor?.click).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

```
cd frontend && npx vitest run src/__tests__/api.download.test.ts
```

Expected: FAIL (api.downloadGP5 is not a function)

- [ ] **Step 3: `frontend/src/lib/api.ts`에 다운로드 함수 추가**

`getToken()` 함수 앞에 `downloadBlob` 헬퍼 추가, `api` 객체에 두 메서드 추가:

```typescript
// api.ts — authHeaders() 함수 바로 다음, request<T>() 이전에 추가
async function downloadBlob(url: string, filename: string): Promise<void> {
  const res = await fetch(url, { headers: authHeaders() })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  const blob = await res.blob()
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  a.click()
  URL.revokeObjectURL(href)
}
```

`api` 객체 끝 `syncFile` 다음에 추가:

```typescript
  async downloadGP5(fileId: string, filename: string): Promise<void> {
    await downloadBlob(`/files/${fileId}/download`, filename)
  },

  async downloadMIDI(fileId: string, filename: string): Promise<void> {
    await downloadBlob(`/files/${fileId}/export/midi`, filename)
  },
```

- [ ] **Step 4: api.ts 테스트 통과 확인**

```
cd frontend && npx vitest run src/__tests__/api.download.test.ts
```

Expected: PASS

- [ ] **Step 5: ExportMenu 테스트 작성**

새 파일 `frontend/src/__tests__/ExportMenu.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  api: {
    downloadGP5: vi.fn().mockResolvedValue(undefined),
    downloadMIDI: vi.fn().mockResolvedValue(undefined),
  },
}))

import ExportMenu from '../components/Editor/ExportMenu'

describe('ExportMenu', () => {
  const onPrint = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('GP5/PDF/MIDI 버튼 세 개 렌더링', () => {
    render(<ExportMenu fileId="f1" onPrint={onPrint} />)
    expect(screen.getByRole('button', { name: /GP5/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /PDF/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /MIDI/i })).toBeInTheDocument()
  })

  it('fileId 없으면 GP5/MIDI 버튼 비활성화', () => {
    render(<ExportMenu fileId={null} onPrint={onPrint} />)
    expect(screen.getByRole('button', { name: /GP5/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /MIDI/i })).toBeDisabled()
    // PDF는 alphaTab print라 항상 활성
    expect(screen.getByRole('button', { name: /PDF/i })).not.toBeDisabled()
  })

  it('GP5 버튼 클릭 → api.downloadGP5 호출', async () => {
    const { api } = await import('../lib/api')
    render(<ExportMenu fileId="f1" onPrint={onPrint} />)
    await userEvent.click(screen.getByRole('button', { name: /GP5/i }))
    expect(api.downloadGP5).toHaveBeenCalledWith('f1', expect.stringContaining('.gp5'))
  })

  it('PDF 버튼 클릭 → onPrint 호출', async () => {
    render(<ExportMenu fileId="f1" onPrint={onPrint} />)
    await userEvent.click(screen.getByRole('button', { name: /PDF/i }))
    expect(onPrint).toHaveBeenCalled()
  })

  it('MIDI 버튼 클릭 → api.downloadMIDI 호출', async () => {
    const { api } = await import('../lib/api')
    render(<ExportMenu fileId="f1" onPrint={onPrint} />)
    await userEvent.click(screen.getByRole('button', { name: /MIDI/i }))
    expect(api.downloadMIDI).toHaveBeenCalledWith('f1', expect.stringContaining('.mid'))
  })
})
```

- [ ] **Step 6: 테스트 실패 확인**

```
cd frontend && npx vitest run src/__tests__/ExportMenu.test.tsx
```

Expected: FAIL (ExportMenu not found)

- [ ] **Step 7: `ExportMenu.tsx` 구현**

```tsx
// frontend/src/components/Editor/ExportMenu.tsx
import { useState } from 'react'
import { api } from '../../lib/api'

interface Props {
  fileId: string | null
  onPrint: () => void
}

export default function ExportMenu({ fileId, onPrint }: Props) {
  const [loading, setLoading] = useState<'gp5' | 'midi' | null>(null)

  const handleGP5 = async () => {
    if (!fileId) return
    setLoading('gp5')
    try {
      await api.downloadGP5(fileId, 'score.gp5')
    } catch (e) {
      console.error('GP5 다운로드 실패', e)
    } finally {
      setLoading(null)
    }
  }

  const handleMIDI = async () => {
    if (!fileId) return
    setLoading('midi')
    try {
      await api.downloadMIDI(fileId, 'score.mid')
    } catch (e) {
      console.error('MIDI 다운로드 실패', e)
    } finally {
      setLoading(null)
    }
  }

  return (
    <span style={{ display: 'inline-flex', gap: 4, marginLeft: 8 }}>
      <button onClick={handleGP5} disabled={!fileId || loading === 'gp5'}>
        {loading === 'gp5' ? '…' : 'GP5 저장'}
      </button>
      <button onClick={onPrint}>PDF 저장</button>
      <button onClick={handleMIDI} disabled={!fileId || loading === 'midi'}>
        {loading === 'midi' ? '…' : 'MIDI 저장'}
      </button>
    </span>
  )
}
```

- [ ] **Step 8: ExportMenu 테스트 통과 확인**

```
cd frontend && npx vitest run src/__tests__/ExportMenu.test.tsx
```

Expected: PASS

- [ ] **Step 9: ScoreViewer 통합 테스트 추가**

`frontend/src/__tests__/ScoreViewer.test.tsx`에 테스트 추가:

```typescript
// 기존 test 두 개 이후에 추가
test('gp5Buffer 있으면 GP5/PDF/MIDI 버튼 표시', () => {
  render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)
  expect(screen.getByRole('button', { name: /GP5/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /PDF/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /MIDI/i })).toBeInTheDocument()
})
```

- [ ] **Step 10: ScoreViewer.tsx에 ExportMenu 통합**

`ScoreViewer.tsx` 상단 import에 추가:
```typescript
import ExportMenu from './ExportMenu'
```

`useEditorStore` 디스트럭처링에 `fileId` 확인 (이미 있음).

툴바 `<div>` 안에서 재생 버튼과 저장 상태 표시 사이에 ExportMenu 추가:

```tsx
// 기존:
<div style={{ padding: '8px 0', display: 'flex', gap: 8, alignItems: 'center' }}>
  <button onClick={() => apiRef.current?.playPause()} disabled={!loaded}>
    {playing ? '일시정지' : '재생'}
  </button>
  <span style={{ fontSize: 12, color: '#888', marginLeft: 8 }}>
    {saveStatus === 'saving' ? '저장 중…' : saveStatus === 'saved' ? '저장됨' : saveStatus === 'error' ? '저장 실패' : ''}
  </span>
</div>

// 교체:
<div style={{ padding: '8px 0', display: 'flex', gap: 8, alignItems: 'center' }}>
  <button onClick={() => apiRef.current?.playPause()} disabled={!loaded}>
    {playing ? '일시정지' : '재생'}
  </button>
  <ExportMenu
    fileId={fileId}
    onPrint={() => apiRef.current?.print()}
  />
  <span style={{ fontSize: 12, color: '#888', marginLeft: 8 }}>
    {saveStatus === 'saving' ? '저장 중…'
      : saveStatus === 'saved' ? '저장됨'
      : saveStatus === 'error' ? '저장 실패'
      : ''}
  </span>
</div>
```

- [ ] **Step 11: 전체 프론트 테스트 통과 확인**

```
cd frontend && npx vitest run
```

Expected: 모두 PASS

- [ ] **Step 12: 커밋**

```bash
git add frontend/src/lib/api.ts \
        frontend/src/components/Editor/ExportMenu.tsx \
        frontend/src/components/Editor/ScoreViewer.tsx \
        frontend/src/__tests__/ExportMenu.test.tsx \
        frontend/src/__tests__/api.download.test.ts \
        frontend/src/__tests__/ScoreViewer.test.tsx
git commit -m "feat: ExportMenu — GP5/PDF/MIDI 내보내기 버튼 + api 다운로드 함수"
```

---

## 범위 외 (Phase 3 이후)

- **MP3/WAV 내보내기**: alphaSynth 오디오 녹화 or 서버사이드 FluidSynth 필요. 별도 계획 필요.
