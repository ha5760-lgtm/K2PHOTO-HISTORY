// K2 PHOTO History - 디자인 컬러 테마
// <head> 에서 동기 로드 → 첫 렌더 전에 저장된 색을 적용 (깜빡임 방지)
// 모든 색은 CSS 변수(--primary*, --sidebar-*)로 연결돼 있어 여기서 값만 바꾸면 전체가 바뀜

(function () {
    const DEFAULT_ACCENT = '#4361ee';
    const ACCENTS = [
        { name: 'Indigo', hex: '#4361ee' },
        { name: 'Samsung Blue', hex: '#1428a0' },
        { name: 'Ocean', hex: '#0284c7' },
        { name: 'Teal', hex: '#0d9488' },
        { name: 'Emerald', hex: '#059669' },
        { name: 'Violet', hex: '#7c3aed' },
        { name: 'Rose', hex: '#e11d48' },
        { name: 'Orange', hex: '#ea580c' },
        { name: 'Slate', hex: '#475569' },
    ];
    const SIDEBARS = [
        { key: 'navy', label: 'Navy' },
        { key: 'black', label: 'Black' },
        { key: 'accent', label: 'Accent' },
        { key: 'light', label: 'Light' },
    ];

    const read = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
    const write = (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { /* noop */ } };

    function toRgb(hex) {
        const h = hex.replace('#', '');
        const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
        return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }
    const toHex = (rgb) => '#' + rgb.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
    // ratio 만큼 target 색 쪽으로 섞기
    const mix = (hex, target, ratio) => toHex(toRgb(hex).map((v, i) => v + (target[i] - v) * ratio));
    const isHex = (v) => /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v || '');

    function sidebarVars(style, accent) {
        switch (style) {
            case 'black':
                return { bg: '#0b0d12', hover: '#171a22', text: '#9aa3b2', strong: '#ffffff', border: 'rgba(255,255,255,0.07)' };
            case 'accent': {
                const bg = mix(accent, [8, 10, 20], 0.72);
                return { bg, hover: mix(bg, [255, 255, 255], 0.08), text: mix(accent, [255, 255, 255], 0.65), strong: '#ffffff', border: 'rgba(255,255,255,0.1)' };
            }
            case 'light':
                return { bg: '#ffffff', hover: mix(accent, [255, 255, 255], 0.9), text: '#475569', strong: '#0f172a', border: '#e2e8f0' };
            default:
                return { bg: '#1a1f2e', hover: '#252b3d', text: '#a0aec0', strong: '#ffffff', border: 'rgba(255,255,255,0.08)' };
        }
    }

    function apply(opts = {}) {
        const accent = isHex(opts.accent) ? opts.accent.toLowerCase() : (isHex(read('k2ph.accent')) ? read('k2ph.accent') : DEFAULT_ACCENT);
        const sidebar = opts.sidebar || read('k2ph.sidebarStyle') || 'navy';
        const root = document.documentElement.style;
        root.setProperty('--primary', accent);
        root.setProperty('--primary-rgb', toRgb(accent).join(', '));
        root.setProperty('--primary-light', mix(accent, [255, 255, 255], 0.3));
        root.setProperty('--primary-dark', mix(accent, [0, 0, 0], 0.15));
        const sb = sidebarVars(sidebar, accent);
        root.setProperty('--bg-sidebar', sb.bg);
        root.setProperty('--bg-sidebar-hover', sb.hover);
        root.setProperty('--sidebar-text', sb.text);
        root.setProperty('--sidebar-text-strong', sb.strong);
        root.setProperty('--sidebar-border', sb.border);
        document.documentElement.dataset.sidebar = sidebar;
        if (opts.accent) write('k2ph.accent', accent);
        if (opts.sidebar) write('k2ph.sidebarStyle', sidebar);
        document.dispatchEvent(new CustomEvent('k2theme', { detail: { accent, sidebar } }));
        return { accent, sidebar };
    }

    function reset() {
        write('k2ph.accent', null);
        write('k2ph.sidebarStyle', null);
        return apply();
    }

    // 다크/라이트 모드도 첫 렌더 전에
    const mode = read('k2ph.theme');
    if (mode) document.documentElement.setAttribute('data-bs-theme', mode);
    apply();

    window.K2Theme = { ACCENTS, SIDEBARS, DEFAULT_ACCENT, apply, reset, current: () => ({
        accent: isHex(read('k2ph.accent')) ? read('k2ph.accent') : DEFAULT_ACCENT,
        sidebar: read('k2ph.sidebarStyle') || 'navy',
    }) };
})();
