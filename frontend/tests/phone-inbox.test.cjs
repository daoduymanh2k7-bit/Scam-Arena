const {test}=require('node:test');
const assert=require('node:assert/strict');
const {remaining}=require('../static/js/phone-inbox.js');
test('OTP lifetime is rounded up, expires and respects revocation',()=>{
  const now=Date.parse('2026-11-24T10:00:00Z');
  assert.equal(remaining({expires_at:'2026-11-24T10:03:00Z'},now),'Còn hiệu lực 3:00');
  assert.equal(remaining({expires_at:'2026-11-24T10:00:00.100Z'},now),'Còn hiệu lực 0:01');
  assert.equal(remaining({expires_at:'2026-11-24T09:59:59Z'},now),'Mã đã hết hiệu lực');
  assert.equal(remaining({revoked_at:'2026-11-24T09:59:00Z',expires_at:'2026-11-24T10:03:00Z'},now),'Mã đã được thay thế');
});
