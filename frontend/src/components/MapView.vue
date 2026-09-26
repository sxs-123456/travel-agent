<script setup lang="ts">
import { onMounted, ref, watch } from "vue";

interface Spot {
  name: string;
  lng: number;
  lat: number;
  kind: string;
}

const props = defineProps<{ spots: Spot[]; city: string; height?: number }>();

const API_BASE = ((import.meta.env.VITE_API_BASE as string) || "").replace(/\/+$/, "");
const amapKey = ref((import.meta.env.VITE_AMAP_KEY as string) || "");
const securityCode = ref((import.meta.env.VITE_AMAP_SECURITY_CODE as string) || "");
const mapEl = ref<HTMLDivElement | null>(null);
const ready = ref(false);
const loadFailed = ref(false);
let map: any = null;

function loadAMap(): Promise<any> {
  return new Promise((resolve, reject) => {
    if (window.AMap) return resolve(window.AMap);
    if (securityCode.value) {
      window._AMapSecurityConfig = { securityJsCode: securityCode.value };
    }
    const s = document.createElement("script");
    s.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(amapKey.value)}`;
    s.async = true;
    s.onload = () => resolve(window.AMap);
    s.onerror = () => reject(new Error("高德地图脚本加载失败"));
    document.head.appendChild(s);
  });
}

async function render() {
  if (!amapKey.value || !mapEl.value) return;
  try {
    const AMap = await loadAMap();
    const center = props.spots[0]
      ? [props.spots[0].lng, props.spots[0].lat]
      : [116.397, 39.918];
    map = new AMap.Map(mapEl.value, { zoom: 12, center });
    props.spots.forEach((sp, i) => {
      const marker = new AMap.Marker({
        position: [sp.lng, sp.lat],
        title: `${sp.kind} · ${sp.name}`,
        map,
      });
      marker.setLabel({
        content: `${i + 1}. ${sp.name}`,
        direction: "top",
        offset: new AMap.Pixel(0, -4),
      });
    });
    if (props.spots.length > 1) map.setFitView();
    ready.value = true;
    loadFailed.value = false;
  } catch {
    // 加载/渲染失败（如 key 类型不匹配）：降级为坐标列表，不让地图区域空白。
    ready.value = false;
    loadFailed.value = true;
  }
}

async function initializeMap() {
  if (!amapKey.value) {
    try {
      const response = await fetch(`${API_BASE}/api/public-config`, { cache: "no-store" });
      if (response.ok) {
        const config = await response.json();
        amapKey.value = config.amap_js_key || "";
        securityCode.value = config.amap_js_security_code || "";
      }
    } catch {
      // Public configuration is optional; the coordinate list remains available.
    }
  }
  if (amapKey.value) await render();
  else loadFailed.value = true;
}

onMounted(initializeMap);
watch(
  () => props.spots,
  () => {
    if (ready.value && amapKey.value) render();
  },
  { deep: true }
);
</script>

<template>
  <div>
    <div v-if="!amapKey || loadFailed" class="tp-empty-map">
      <div>
        <p class="tp-section-title">📍 行程地理坐标</p>
        <p class="tp-muted">
          高德地图暂不可用（{{ !amapKey ? "未配置 JS API Key" : "Key 加载失败，请检查 Key 类型、域名限制和安全码" }}），
          已降级为坐标列表。在 Railway 服务变量中设置 AMAP_JS_API_KEY（Web 端 JS API Key）和
          AMAP_JS_API_SECURITY_CODE，等服务重启后刷新页面；请将 Key 的允许域名限制为本站。
        </p>
        <ul style="text-align: left; margin: 10px 0 0; padding-left: 18px">
          <li v-for="(sp, i) in spots" :key="i" style="margin-bottom: 4px">
            <b>{{ i + 1 }}. {{ sp.name }}</b>
            <span class="tp-muted">（{{ sp.kind }}）</span>
            — {{ sp.lng.toFixed(3) }}, {{ sp.lat.toFixed(3) }}
          </li>
        </ul>
      </div>
    </div>
    <div
      v-else
      ref="mapEl"
      :style="{ width: '100%', height: (height || 360) + 'px', borderRadius: '12px' }"
    ></div>
  </div>
</template>
