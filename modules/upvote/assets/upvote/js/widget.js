(() => {
  const containers = Array.from(document.querySelectorAll('[data-upvote]'));
  if (!containers.length) return;

  const hasMoved = { value: false };
  const started = Date.now();
  const movementHandler = () => { hasMoved.value = true; };
  document.addEventListener('mousemove', movementHandler, { once: true });
  document.addEventListener('touchmove', movementHandler, { once: true });

  containers.forEach((container) => {
    const slug = container.getAttribute('data-slug');
    const endpoint = container.getAttribute('data-endpoint');
    const infoEndpoint = container.getAttribute('data-info-endpoint');
    const upvotedTitle = container.getAttribute('data-upvoted-title') || '';
    const form = container.querySelector('form');
    const button = container.querySelector('.upvote-button');
    const countEl = container.querySelector('.upvote-count');
    if (!slug || !endpoint || !infoEndpoint || !form || !button || !countEl) {
      return;
    }

    const readHidden = (name) => {
      const el = form.querySelector(`input[name="${name}"]`);
      return el && typeof el.value === 'string' ? el.value : '';
    };

    const title = readHidden('title');
    const permalink = readHidden('permalink');
    const dateISO = readHidden('dateISO');

    const updateState = ({ upvote_count, upvoted }) => {
      if (typeof upvote_count === 'number') {
        countEl.textContent = upvote_count.toString();
      }
      if (upvoted) {
        button.disabled = true;
        button.classList.add('upvote-button--active');
        if (upvotedTitle) button.title = upvotedTitle;
      }
    };

    const infoUrl = new URL(infoEndpoint, window.location.origin);
    infoUrl.searchParams.set('slug', slug);
    if (title) infoUrl.searchParams.set('title', title);
    if (permalink) infoUrl.searchParams.set('permalink', permalink);
    if (dateISO) infoUrl.searchParams.set('dateISO', dateISO);

    fetch(infoUrl.toString(), { credentials: 'include' })
      .then((resp) => resp.ok ? resp.json() : null)
      .then((data) => {
        if (!data) return;
        updateState(data);
      })
      .catch(() => {});

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (button.disabled) return;
      if (!hasMoved.value || Date.now() - started < 2000) return;

      fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slug, title, permalink, dateISO }),
        credentials: 'include'
      })
        .then((resp) => resp.ok ? resp.json() : null)
        .then((data) => {
          if (!data) return;
          updateState(data);
        })
        .catch(() => {});
    });
  });
})();
