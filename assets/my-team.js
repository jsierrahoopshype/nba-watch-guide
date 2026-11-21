/* "My team" on the hub. Included right after the picker and the card
   template, without defer, so it runs while the page is parsed: the saved
   team's next-game card is copied into the slot before anything below it
   is laid out, so nothing moves once painted. The team is kept on this
   device only (localStorage hm-watch-team); nothing is fetched or sent.
   watch-guide.js wires the picker, Clear and the team pages' button. */
(function () {
  'use strict';
  var slug = '';
  try { slug = localStorage.getItem('hm-watch-team') || ''; } catch (e) { return; }
  if (!/^[a-z0-9-]{2,40}$/.test(slug)) return;
  var tpl = document.getElementById('my-team-cards');
  var slot = document.querySelector('[data-my-team-slot]');
  if (!tpl || !tpl.content || !slot) return;
  var card = tpl.content.querySelector('[data-team="' + slug + '"]');
  if (!card) return;
  slot.appendChild(card.cloneNode(true));
  var root = document.querySelector('[data-my-team-root]');
  if (root) root.setAttribute('data-saved', slug);
  var select = document.querySelector('[data-my-team-select]');
  if (select) select.value = slug;
})();
