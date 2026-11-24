document.querySelectorAll('.study-form').forEach(form => {
  form.addEventListener('submit', () => {
    const button = form.querySelector('button');
    if (button) { button.disabled = true; button.textContent = '保存中…'; }
  });
});
const choiceGroupSelector = '.study-options, .quiz-form .options';
if (document.activeElement === document.body) {
  document.querySelector(choiceGroupSelector)?.querySelector('input[type="radio"]')?.focus({preventScroll: true});
}

function advanceQuizQuestion(group) {
  const next = group.closest('.question').nextElementSibling;
  if (!next?.classList.contains('question')) {
    group.closest('form').querySelector('.submit-bar button').focus();
    return;
  }
  const input = next.querySelector('input:checked') || next.querySelector('input');
  next.scrollIntoView({block: 'start'});
  input?.focus({preventScroll: true});
}

function handleChoiceKey(event, group) {
  const choices = [...group.querySelectorAll('input[type="radio"]')];
  if (!choices.length) return false;
  const current = choices.indexOf(document.activeElement);
  const digit = /^[1-4]$/.test(event.key) ? event.key : /^Numpad([1-4])$/.exec(event.code)?.[1];
  let index;
  if (digit) {
    index = Number(digit) - 1;
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    const direction = event.key === 'ArrowDown' ? 1 : -1;
    index = current === -1 ? 0 : (current + direction + choices.length) % choices.length;
  } else if (event.key === 'Enter') {
    event.preventDefault();
    if (event.repeat) return true;
    const choice = choices[current] || choices.find(input => input.checked) || choices[0];
    choice.checked = true;
    if (choice.form.classList.contains('quiz-form')) {
      advanceQuizQuestion(group);
    } else if (!choice.form.querySelector('button').disabled) {
      choice.form.requestSubmit();
    }
    return true;
  } else {
    return false;
  }
  const choice = choices[index];
  if (choice) {
    event.preventDefault();
    choice.checked = true;
    choice.focus();
  }
  return true;
}

document.addEventListener('keydown', event => {
  if (event.defaultPrevented || event.isComposing || event.ctrlKey || event.altKey || event.metaKey) return;
  const target = document.activeElement;
  const group = target?.closest(choiceGroupSelector)
    || (target === document.body ? document.querySelector('.study-options') : null);
  if (group && handleChoiceKey(event, group)) return;
  if (event.repeat) return;
  const tag = target?.tagName;
  if (!['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) && ['ArrowLeft', 'ArrowRight'].includes(event.key) && document.querySelector('.memory-card')) {
    event.preventDefault();
    const form = document.querySelector(event.key === 'ArrowLeft' ? '.memory-previous' : '.memory-action');
    if (form && !form.querySelector('button').disabled) form.requestSubmit();
    return;
  }
  if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A'].includes(tag)) return;
  if (event.key === 'Enter') {
    const form = document.querySelector('.study-form');
    if (form) { event.preventDefault(); form.requestSubmit(); }
  }
});
document.querySelectorAll('.restart-study').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm('重新开始会清空这次闯关过程，已获得的背诵记录仍保留。确定重新开始？')) event.preventDefault();
  });
});
