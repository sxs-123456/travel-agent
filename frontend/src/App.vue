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
    <main v-if="!showResult">
      <section id="planner" class="hero">
        <img class="hero-illustration" src="/hero-landmarks.svg" alt="" aria-hidden="true" />
        <div class="hero-content">
          <h1>下一站，<em>去哪里？</em></h1>
          <p class="hero-lead">告诉我们你想去哪、何时出发和喜欢什么。<br />把一句旅行想法，变成一份可以查看的逐日计划。</p>
          <PlanForm
            :loading="loading"
            :error="error"
            :initial-query="lastQuery"
            @submit="generate"
            @edit="error = ''"
          />
        </div>
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
      </section>
    </main>

    <main v-else class="result-page">
      <template v-if="result">
        <div class="result-intro">
          <a class="result-back" href="#/">← 返回首页</a>
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

    <footer class="site-footer"><p>把旅行想法，慢慢变成计划。</p><small>AI 生成内容和费用仅供规划参考，实际安排请以官方信息为准。</small></footer>
  </div>
</template>
