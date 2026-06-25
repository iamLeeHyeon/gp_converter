# 화음(다음 동시발음) GP5 변환 설계

## 배경

`app/pipeline/musicxml_to_gp.py`는 지금까지 MusicXML의 화음(Chord)에서 최고음(MIDI 최댓값) 하나만 골라 쓰고 나머지 음은 버렸다(MVP 단순화로 처음부터 의도된 동작). 실제 변환 결과를 사용자가 직접 확인하면서, 마디100처럼 Audiveris가 4음 화음(G4+C5+E5+B5 등)을 정확히 인식해놓은 곡에서도 GP5에는 1개 음만 남는 문제가 드러났다. 이제 화음의 모든 음을 살려서 서로 다른 현/프렛에 동시발음으로 배정해야 한다.

## 목표

- MusicXML Chord의 모든 구성음을 GP5의 한 Beat 안에 여러 Note로 표현한다.
- 표준 기타 튜닝(6현, MIDI 64/59/55/50/45/40), 현당 0~24프렛 제약, 한 Beat 안에서 같은 현을 두 음이 동시에 못 쓰는 제약을 지킨다.
- 기존 단일음 경로(쉼표, 이음줄, 마디 그룹화, 유령 쉼표 제거, tab_hints)는 그대로 유지한다.

## 데이터 모델 변경

`NoteEvent.midi: Optional[int]` → `NoteEvent.pitches: List[int]`로 바꾼다.

- 단일음: `pitches`가 길이 1인 리스트.
- 화음: `pitches`가 길이 2 이상, **MIDI 내림차순(높은음 먼저)** 정렬.
- 쉼표: `pitches`가 빈 리스트(`is_rest=True`와 함께).

`is_rest`, `ql`, `tied` 필드는 그대로 둔다. 코드 전체에 단일 `tie`만 있는 MusicXML 구조상(music21 Chord 객체는 화음 전체에 대해 하나의 tie 속성을 가짐), 화음의 모든 구성음에 동일한 `tied` 값을 적용한다 — 음별로 다른 tie 상태는 실무에서 거의 없으므로 단순화한다.

## 현 배정 알고리즘 — `_assign_chord_strings`

```python
def _assign_chord_strings(
    pitches: List[int],  # 내림차순(높은음 먼저)
    strings: List[Tuple[int, int]],
) -> List[Optional[Tuple[int, int]]]:
    """화음의 각 음에 (현 번호, 프렛)을 배정한다.

    높은음부터 처리하며, 각 음마다 후보 현을 프렛 낮은순으로 정렬해두고
    그리디하게 비어있는 첫 현을 잡는다(1순위 막히면 2,3순위 시도).
    이미 화음 내 다른 음이 그 현을 썼으면 다음 후보로 넘어간다.
    모든 후보 현이 막히면 그 음은 None(스킵 표시)을 반환한다.
    """
    used_strings: set[int] = set()
    result: List[Optional[Tuple[int, int]]] = []
    for midi in pitches:
        candidates = sorted(
            (midi - sval, snum) for snum, sval in strings if 0 <= midi - sval <= 24
        )
        for fret, snum in candidates:
            if snum not in used_strings:
                used_strings.add(snum)
                result.append((snum, fret))
                break
        else:
            result.append(None)
    return result
```

`None`이 반환된 음은 `_fill_voice`에서 건너뛰고(기존 단일음 범위밖 처리와 동일하게) 경고 로그를 남긴다. 화음의 나머지 음은 정상적으로 들어간다 — 화음 전체를 버리지 않는다.

이 알고리즘은 완전탐색(조합 최적화)이 아니라 그리디+fallback이라서, 극단적인 경우(예: 같은 프렛을 원하는 음이 5개 이상 겹침) 이론상 더 나은 배정이 존재해도 못 찾을 수 있다. 실용적으로는 일반적인 기타 화음(최대 6음, 보통 3~4음)에서 충분히 잘 동작한다.

## `_fill_voice` 변경

기존에는 이벤트마다 Note 1개를 만들었다. 이제 `pitches` 길이에 따라 분기한다:

- `len(pitches) == 0` (쉼표): 기존과 동일, `BeatStatus.rest`, `beat.notes = []`.
- `len(pitches) == 1` (단일음): 기존과 동일 — `use_hints`이면 tab_hints 우선, 없으면 `_midi_to_string_fret`.
- `len(pitches) >= 2` (화음): tab_hints는 **항상 무시**한다(힌트 1개로 다중음을 표현할 수 없음). `_assign_chord_strings`로 배정받은 (현,프렛) 각각에 대해 `Note` 객체를 만들어 `beat.notes`에 전부 담는다. `NoteType`은 화음 전체의 `tied` 값을 모든 구성음에 동일 적용.

## tab_hints 개수 검증 변경

현재 `total_notes`(tab_hints 길이와 비교하는 기준)는 "쉼표를 제외한 전체 이벤트 수"다. 화음 이벤트는 힌트 1개로 표현할 수 없으므로, `total_notes`는 **단일음 이벤트만** 센다(화음·쉼표 이벤트는 제외). 화음이 하나라도 있는 마디에서는 tab_hints 길이가 "단일음 개수"와 맞아야 하고, 화음 이벤트 자리는 항상 새 알고리즘으로 채워진다.

## 영향받지 않는 부분

쉼표 처리, 이음줄(tie) 마킹, 마디 그룹화(실제 박자 따름), 유령 선행 쉼표 제거, 조표/박자 전파, 옥타브 보정(-12)은 전부 그대로다. `_extract_events`에서 `Note`/`Chord` 판별 후 `pitches` 리스트를 만드는 부분만 바뀐다.

## 테스트 계획

1. 4음 화음(서로 다른 현에 자연스럽게 배정되는 경우) — 모든 음이 살아서 한 Beat에 들어가는지.
2. 화음 내 두 음이 1순위로 같은 현을 원하는 충돌 케이스 — fallback으로 둘 다 들어가는지(2순위 현 사용).
3. 화음 안 한 음이 어떤 현으로도 표현 못 하는 극단적 케이스 — 그 음만 스킵 + 경고 로그, 나머지 음은 살아있는지.
4. tab_hints가 있고 화음이 섞인 마디 — 화음 이벤트는 힌트 무시하고 새 알고리즘 사용, 단일음 이벤트는 힌트 그대로 적용되는지.
5. 기존 단일음/쉼표 테스트가 `pitches` 리스트 모델로 바뀐 뒤에도 전부 통과하는지(회귀 없음).
