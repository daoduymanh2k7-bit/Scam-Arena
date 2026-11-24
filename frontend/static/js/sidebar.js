(() => {
  const account = document.getElementById('account-controls');
  document.addEventListener('click', event => {
    if (!account.contains(event.target)) account.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && account.open) {
      account.open = false;
      account.querySelector('summary').focus();
    }
  });
  window.addEventListener('message', event => {
    const frame=document.getElementById('practice-admin-frame');
    if(event.origin===location.origin && event.source===frame?.contentWindow && event.data?.type==='arena:catalog-updated')
      document.dispatchEvent(new CustomEvent('arena:catalog-updated'));
  });
  document.addEventListener('arena:viewchange', event => {
    account.open = false;
    if(event.detail.mode==='history')window.ArenaHistory?.refreshAll();
    if(event.detail.mode==='practice') {
      const frame=document.getElementById('practice-admin-frame');
      if(!frame.getAttribute('src'))frame.src=frame.dataset.src;
    }
  });
})();
