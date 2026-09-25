<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import type { NaturalTripResponse } from "@/types/trip";
import { createTripPlanFromText } from "@/api/client";
import PlanForm from "@/components/PlanForm.vue";
import TripResult from "@/components/TripResult.vue";

const STORAGE_KEY = "ai-trip-planner:last-plan";

function loadSaved(): (NaturalTripResponse & { query: string }) | null {
  try {
    const value = sessionStorage.getItem(STORAGE_KEY);
    if (!value) return null;
    const parsed = JSON.parse(value);
    return parsed?.plan?.days && parsed?.request?.city ? parsed : null;
  } catch {
    return null;
  }
}

const saved = loadSaved();
const result = ref<NaturalTripResponse | null>(
  saved ? { request: saved.request, plan: saved.plan } : null
);
const lastQuery = ref(saved?.query ?? "");
const showResult = ref(window.location.hash === "#/plan");
const loading = ref(false);
const error = ref("");

function syncRoute() {
  showResult.value = window.location.hash === "#/plan";
  window.scrollTo({ top: 0, behavior: "instant" });
}

onMounted(() => window.addEventListener("hashchange", syncRoute));
onUnmounted(() => window.removeEventListener("hashchange", syncRoute));

async function generate(query: string) {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  try {
    const response = await createTripPlanFromText(query);
    result.value = response;
    lastQuery.value = query;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ ...response, query }));
    } catch {
      // The result remains available in this tab even if browser storage is full.
    }
    showResult.value = true;
    window.location.hash = "/plan";
    window.scrollTo({ top: 0, behavior: "instant" });
  } catch (cause: unknown) {
    error.value = cause instanceof Error ? cause.message : "行程生成失败，请稍后重试。";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="site-shell">
    <header class="site-nav" :class="{ 'site-nav-result': showResult }">
      <a class="site-brand" href="#/" aria-label="AI Trip Planner 首页">
        <span class="site-brand-mark" aria-hidden="true">✳</span>
        <span>漫游<span class="site-brand-dot">.</span></span>
      </a>
      <nav class="site-links" aria-label="主导航">
        <template v-if="!showResult">
          <a href="#features">了解功能</a>
          <a href="#how-it-works">使用方法</a>
        </template>
        <a v-if="result" href="#/plan">我的行程</a>
      </nav>
      <a class="site-nav-cta" :href="showResult ? '#/' : '#planner'">
        {{ showResult ? "重新规划" : "开始规划" }} <span aria-hidden="true">↗</span>
      </a>
    </header>

    <main v-if="!showResult">
      <section id="planner" class="hero">
        <video class="hero-video" autoplay muted loop playsinline preload="metadata" aria-hidden="true" tabindex="-1">
          <source src="/hero-china-karst.mp4" type="video/mp4" />
        </video>
        <div class="hero-atmosphere" aria-hidden="true">
          <div class="hero-glow"></div>
          <div class="hero-cloud hero-cloud-one"></div>
          <div class="hero-cloud hero-cloud-two"></div>
        </div>
        <div class="hero-content">
          <span class="hero-eyebrow"><span></span> AI TRIP PLANNER</span>
          <h1>下一站，<em>去哪里？</em></h1>
          <p class="hero-lead">告诉我们你想去哪、何时出发和喜欢什么。<br />把一句旅行想法，变成一份可以查看的逐日计划。</p>
          <PlanForm
            :loading="loading"
            :error="error"
            :initial-query="lastQuery"
            @submit="generate"
            @edit="error = ''"
          />
          <p class="hero-assurance">目的地 · 每日路线 · 地图 · 预算参考</p>
        </div>
        <svg class="hero-landscape" viewBox="0 0 1440 330" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
          <path d="M0 250Q130 185 260 226T505 218Q640 174 735 218T940 201Q1100 145 1240 209T1440 197V330H0Z" fill="#9b9783" opacity=".48"/>
          <path d="M0 284Q135 219 270 257T515 239Q640 208 742 253T946 234Q1100 185 1245 247T1440 225V330H0Z" fill="#766b58" opacity=".72"/>
          <path d="M0 318Q160 252 320 304T615 282Q750 246 920 288T1200 268Q1320 243 1440 288V330H0Z" fill="#493e33"/>
          <path d="M55 270l30-45 28 9 25-44 40 13 19-26 26 18 13 56m-169 19h178m-151-44v-21m47 12v-23m47-4v-20" fill="none" stroke="#312c26" stroke-width="7" stroke-linejoin="round" opacity=".62"/>
          <path d="M1022 236l52-70 45 57 37-94 67 105m-198 1h229" fill="none" stroke="#37342c" stroke-width="8" stroke-linejoin="round" opacity=".55"/>
          <path d="M1245 251h111m-95 0v-54h79v54m-86-54 46-38 48 38m-80-9v-18h64v18m-49-40h35m-17 0v-22" fill="none" stroke="#292923" stroke-width="7" stroke-linejoin="round" opacity=".65"/>
          <path d="M366 294q80-75 164-24m-175 10q91-61 182-1" fill="none" stroke="#e8d4aa" stroke-width="7" opacity=".68"/>
        </svg>
        <div class="hero-bottom-label">为每一次出发，留一点期待。</div>
      </section>

      <section id="features" class="info-section">
        <div class="info-heading">
          <span class="section-kicker">WHY PLAN WITH US</span>
          <h2>从想法，到看得见的旅程</h2>
          <p>输入自然语言需求，规划器结合目的地信息整理路线、住宿、天气和费用参考。</p>
        </div>
        <div class="feature-grid">
          <article class="feature-card"><span class="feature-number">01</span><h3>一句话就能开始</h3><p>直接描述出发地、目的地、日期和旅行偏好，无需逐项填写表单。</p></article>
          <article class="feature-card"><span class="feature-number">02</span><h3>逐日安排更清楚</h3><p>查看每天的景点、餐饮与住宿建议，并在地图上了解行程位置。</p></article>
          <article class="feature-card"><span class="feature-number">03</span><h3>费用有据可看</h3><p>展示门票、住宿、餐饮与交通的预算拆分；估算项会明确标注。</p></article>
        </div>
      </section>
      <section id="how-it-works" class="closing-section">
        <span class="section-kicker">HOW IT WORKS</span>
        <h2>说出你的下一段旅程。</h2>
        <p>写清目的地与出发、返程日期，就可以开始规划。细节越具体，建议越贴近你的想法。</p>
        <a class="closing-cta" href="#planner">开始规划 <span aria-hidden="true">↗</span></a>
      </section>
    </main>

    <main v-else class="result-page">
      <template v-if="result">
        <div class="result-intro">
          <span class="section-kicker">YOUR ITINERARY</span>
          <h1>你的 {{ result.request.city }} 之旅，<em>已就绪。</em></h1>
          <p class="result-original">“{{ lastQuery }}”</p>
          <div class="result-facts">
            <span v-if="result.request.origin_city">从 {{ result.request.origin_city }} 出发</span>
            <span>{{ result.request.start_date }} — {{ result.request.end_date }}</span>
            <span>{{ result.plan.days.length }} 天行程</span>
            <span>{{ result.request.travelers }} 人出行</span>
            <span>{{ result.request.budget_level }}预算</span>
          </div>
        </div>
        <div class="result-content"><TripResult :plan="result.plan" /></div>
      </template>
      <div v-else class="result-missing">
        <span class="section-kicker">YOUR ITINERARY</span>
        <h1>还没有生成行程</h1>
        <p>回到首页，说说你的旅行计划吧。</p>
        <a class="closing-cta" href="#/">返回首页 <span aria-hidden="true">↗</span></a>
      </div>
    </main>

    <footer class="site-footer"><span>漫游<span class="site-brand-dot">.</span></span><p>把旅行想法，慢慢变成计划。</p><small>AI 生成内容和费用仅供规划参考，实际安排请以官方信息为准。<a href="https://www.pexels.com/video/drone-view-of-misty-karst-mountains-in-china-38368356/" target="_blank" rel="noopener noreferrer">视频：Pexels</a></small></footer>
  </div>
</template>
