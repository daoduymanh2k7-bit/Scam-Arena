const {test}=require('node:test');
const assert=require('node:assert/strict');
const E=require('../static/js/practice-editor-core.js');
test('creating and duplicating a scenario creates independent unpublished editor documents',()=>{
 const original=E.fresh(),copy=E.duplicate(original);
 assert.notEqual(original.id,copy.id);
 copy.stages[0].opening_line='Different';
 assert.equal(original.stages[0].opening_line,'');
 assert.equal(copy.version,1);
});
test('preview respects authored branches and prevents endless loops',()=>{
 const doc=E.fresh();const first=E.preview(doc,'intro','comply');
 assert.equal(first.current,'END_SAFE');assert.equal(first.ended,true);
 doc.stages[0].transitions.find(t=>t.on_intent==='comply').next_stage_id='intro';
 let state={current:'intro',visits:{},count:0,unknown:0};
 for(let i=0;i<12;i++)state=E.preview(doc,state.current,'comply',state.visits,state.count,state.unknown);
 assert.equal(state.current,'END_NEUTRAL');assert.equal(state.ended,true);
});
test('deleting a referenced step can be blocked before losing transitions, flags or score rules',()=>{
 const doc=E.fresh();doc.stages.push(E.stage('next'));doc.stages[0].transitions[0].next_stage_id='next';
 doc.red_flags=[{id:'test',stage_id:'next'}];doc.scoring.rules[0].stage_id='next';
 assert.deepEqual(E.references(doc,'next'),['intro','dấu hiệu test','luật điểm']);
});
test('preview uses timeout for an unconfigured reaction',()=>{
 const doc=E.fresh();doc.stages[0].max_turns=1;doc.stages[0].transitions=[];
 assert.equal(E.preview(doc,'intro','unknown').current,'END_NEUTRAL');
});
