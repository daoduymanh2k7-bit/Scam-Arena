(() => {
  const history = document.getElementById('sidebar-history-dialog');
  const openHistory = document.getElementById('sidebar-history-open');
  const account = document.getElementById('account-controls');
  openHistory.addEventListener('click', () => {
    if (!history.open) history.showModal();
    window.ArenaHistory?.refreshAll();
  });
  document.getElementById('sidebar-history-close').addEventListener('click', () => history.close());
  history.addEventListener('click', event => { if (event.target === history) history.close(); });
  document.addEventListener('click', event => { if (!account.contains(event.target)) account.open = false; });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && account.open) {
      account.open = false;
      account.querySelector('summary').focus();
    }
  });
})();
