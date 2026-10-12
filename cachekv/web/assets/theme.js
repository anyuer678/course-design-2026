/* webkit/theme.js 1.0 —— 三态主题切换（跟随系统 auto / 亮 light / 暗 dark）。
   零依赖；与 kb.css 3.0 的暗色变量配套。产品页在 <head> 里 kb.css 之后引一行：
       <script src="/static/assets/theme.js"></script>   （前缀按各产品挂载点）
   行为：
   - 立即执行段：读 localStorage('kb-theme')，把 data-theme 设到 <html> 上
     （head 内同步执行，无暗色闪烁）；
   - DOM 就绪后：左下角注入圆形切换按钮，点按 auto→dark→light→auto 循环，
     图标 ◐/🌙/☀️，aria-label 实时报当前态；
   - auto 档删掉 data-theme，交回给 kb.css 的 prefers-color-scheme 媒体查询。 */
(function () {
  'use strict';
  var KEY = 'kb-theme';

  function apply(t) {
    var root = document.documentElement;
    if (t === 'light' || t === 'dark') root.dataset.theme = t;
    else delete root.dataset.theme;          // auto：跟随系统
  }

  var cur;
  try { cur = localStorage.getItem(KEY) || 'auto'; } catch (e) { cur = 'auto'; }
  if (cur !== 'light' && cur !== 'dark') cur = 'auto';
  apply(cur);

  function icon(t)  { return t === 'dark' ? '🌙' : t === 'light' ? '☀️' : '◐'; }
  function label(t) { return t === 'dark' ? '暗色' : t === 'light' ? '亮色' : '跟随系统'; }

  function init() {
    var b = document.createElement('button');
    b.className = 'theme-toggle';
    b.type = 'button';
    b.setAttribute('aria-label', '切换主题（当前：' + label(cur) + '）');
    b.title = '主题：' + label(cur) + '（点击切换）';
    b.textContent = icon(cur);
    b.addEventListener('click', function () {
      cur = cur === 'auto' ? 'dark' : cur === 'dark' ? 'light' : 'auto';
      try { localStorage.setItem(KEY, cur); } catch (e) { /* 隐私模式等：仅本次生效 */ }
      apply(cur);
      b.textContent = icon(cur);
      b.title = '主题：' + label(cur) + '（点击切换）';
      b.setAttribute('aria-label', '切换主题（当前：' + label(cur) + '）');
    });
    document.body.appendChild(b);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
