#!/usr/bin/env python3
"""Test TV + music tools — stations, recommendations, playback."""
import sys, json
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_music_stations,
    _tool_recommend_music,
    _tool_play_music_for_senior,
    _tool_pause_music_for_senior,
    _tool_youtube_search,
    _tool_recommend_tv_content,
    _tool_list_seniors,
)

print('=' * 60)
print('TV + MUSIC — TEST')
print('=' * 60)
print()

seniors = _tool_list_seniors()
test_sid = next((s['id'] for s in seniors if s['id'] in ('268', '282', '287')), '287')
print(f'Test senior: #{test_sid}')
print()

# 1. Stations catalog
print('━━━ 1. get_music_stations ━━━')
all_s = _tool_get_music_stations()
print(f'  groups: {all_s.get("groups")} total: {all_s.get("total")}')
czech = _tool_get_music_stations(group='czech')
print(f'  czech: {czech.get("count")} stanic:')
for s in czech.get('stations', [])[:4]:
    print(f'    • {s["id"]:15s} {s["name"]:18s} | {s["category"]:18s} | {s["mood"]}')
print()

# 2. Recommend music (Ψ(t) aware)
print('━━━ 2. recommend_music (mode-aware) ━━━')
r = _tool_recommend_music(test_sid)
top = r.get('top_recommendation') or {}
reason = r.get('reason', {})
print(f'  → top: {top.get("name")} ({top.get("mood")})')
print(f'  reason: brain_mode={reason.get("brain_mode")}, hour={reason.get("hour")}, target_mood={reason.get("target_mood")}')
alts = r.get('alternatives', [])
if alts:
    print(f'  alternatives: {[a.get("name") for a in alts[:3]]}')

# Override mood
print('\n  with mood_override="meditative":')
r2 = _tool_recommend_music(test_sid, mood_override='meditative')
print(f'  → top: {r2.get("top_recommendation", {}).get("name")} ({r2.get("top_recommendation", {}).get("mood")})')
print()

# 3. Play music (will be skipped or queued)
print('━━━ 3. play_music_for_senior ━━━')
p = _tool_play_music_for_senior(test_sid, 'vltava')
print(f'  → {p}')
print()

# 4. Invalid station
print('━━━ 4. play with invalid station_id ━━━')
p_bad = _tool_play_music_for_senior(test_sid, 'BOGUS_STATION')
print(f'  → {"✓ rejected" if p_bad.get("error") else "✗"}: {p_bad.get("error", "")[:60]}')
print()

# 5. Pause
print('━━━ 5. pause_music_for_senior ━━━')
ps = _tool_pause_music_for_senior(test_sid)
print(f'  → {ps}')
print()

# 6. TV recommendations
print('━━━ 6. recommend_tv_content ━━━')
tv = _tool_recommend_tv_content(test_sid)
print(f'  brain_mode: {tv.get("brain_mode")}, hour: {tv.get("hour")}')
for rec in tv.get('recommendations', [])[:3]:
    print(f'    • {rec.get("category"):10s} | {rec.get("query") or rec.get("station_id"):30s} | {rec.get("reason")}')
print()

# 7. YouTube search (skip if won't work locally)
print('━━━ 7. youtube_search ━━━')
yt = _tool_youtube_search('česká pohádka', limit=3)
if yt.get('error'):
    print(f'  ⚠ {yt["error"][:80]}')
else:
    print(f'  count: {yt.get("count")}')
    for v in yt.get('videos', [])[:3]:
        print(f'    • {(v.get("title") or "")[:60]} ({v.get("duration", "?")})')
print()

print('=' * 60)
print('DONE')
