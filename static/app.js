document.querySelectorAll('.meaning').forEach(button => {
  button.addEventListener('click', () => button.classList.toggle('concealed'));
});
const toggle = document.querySelector('#toggle-meanings');
if (toggle) {
  toggle.addEventListener('click', () => {
    const hide = toggle.textContent.includes('隐藏');
    document.querySelectorAll('.meaning').forEach(button => button.classList.toggle('concealed', hide));
    toggle.textContent = hide ? '显示全部释义' : '隐藏全部释义';
  });
}
document.querySelectorAll('.quiz-form').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm('确认提交答卷？提交后将不能修改。')) {
      event.preventDefault();
    } else {
      const button = form.querySelector('button[type="submit"], .submit-bar button');
      if (button) { button.disabled = true; button.textContent = '正在交卷…'; }
    }
  });
});
