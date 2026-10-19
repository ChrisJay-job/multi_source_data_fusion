from fusion_mvp.engine import FusionSession,load_config

def obs(oid,tid,t,x):
    return dict(observationId=oid,source='radar',detectorId='D',sourceTrackId=tid,aircraftId=None,
        measurementTime=f'2026-04-09T12:00:0{t}Z',longitude=117.2+x/(111320*0.7757),latitude=39.13)

def run_new(new_tid,x=150):
    s=FusionSession('review',load_config())
    s.process('b0','2026-04-09T12:00:00Z',[obs('a','R',0,0)],'replay')
    r=s.process('b1','2026-04-09T12:00:01Z',[obs('b',new_tid,1,x)],'replay')
    return s,r

def test_arbitrary_id_spelling_does_not_bypass_motion_gates():
    a,ra=run_new('new-id');b,rb=run_new('R-v2')
    assert len(ra.tracks)==len(rb.tracks), {'unrelated_id_targets':len(ra.tracks),'suffix_id_targets':len(rb.tracks),'suffix_events':[e.type for e in rb.events]}

def test_handoff_preserves_same_device_one_to_one_assignment():
    s=FusionSession('review',load_config())
    s.process('b0','2026-04-09T12:00:00Z',[obs('a','R',0,0)],'replay')
    r=s.process('b1','2026-04-09T12:00:01Z',[obs('b','R-v2',1,20),obs('c','R-v3',1,30)],'replay')
    handoffs=[e for e in r.events if e.type=='radar_id_swap_handoff']
    fids=[e.fusionId for e in handoffs]
    assert len(fids)==len(set(fids)), {'handoff_fids':fids,'tracks':len(r.tracks)}
