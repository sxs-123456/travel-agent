<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import type { NaturalTripResponse, TripPlan } from "@/types/trip";
import { createTripPlanFromText, TripRequestError } from "@/api/client";
import PlanForm from "@/components/PlanForm.vue";
import PlanHistory from "@/components/PlanHistory.vue";
import TripResult from "@/components/TripResult.vue";
import { downloadTrip } from "@/utils/download";
import {
  deleteSavedTrip,
  loadTripHistory,
  migrateLegacyPlan,
  saveTrip,
  updateSavedTripPlan,
  type SavedTrip,
} from "@/utils/history";

interface FormSubmission {
  query: string;
  startDate?: string;
  endDate?: string;
}

const history = ref<SavedTrip[]>(migrateLegacyPlan());
const currentId = ref(history.value[0]?.id ?? "");
const result = ref<NaturalTripResponse | null>(
  history.value[0] ? { request: history.value[0].request, plan: history.value[0].plan } : null
);
const lastQuery = ref(history.value[0]?.query ?? "");
const route = ref(window.location.hash || "#/");
const loading = ref(false);
const error = ref("");
const missingFields = ref<string[]>([]);

const isPlan = computed(() => route.value === "#/plan");
const isHistory = computed(() => route.value === "#/history");

function syncRoute() {
  route.value = window.location.hash || "#/";
  window.scrollTo({ top: 0, behavior: "instant" });
}

onMounted(() => window.addEventListener("hashchange", syncRoute));
onUnmounted(() => window.removeEventListener("hashchange", syncRoute));

function clearPromptState() {
  error.value = "";
  missingFields.value = [];
}

async function generate(submission: FormSubmission) {
  if (loading.value) return;
  loading.value = true;
  clearPromptState();
  lastQuery.value = submission.query;
  try {
    const response = await createTripPlanFromText(submission.query, submission);
    result.value = response;
    const saved = saveTrip(response, submission.query);
    currentId.value = saved.id;
    const stored = loadTripHistory();
    history.value = stored.some((item) => item.id === saved.id)
      ? stored
      : [saved, ...history.value];
    window.location.hash = "/plan";
  } catch (cause: unknown) {
    error.value = cause instanceof Error
      ? cause.message
      : "\u884c\u7a0b\u751f\u6210\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002";
    missingFields.value = cause instanceof TripRequestError ? cause.missingFields : [];
  } finally {
    loading.value = false;
  }
}

function openSavedTrip(item: SavedTrip) {
  currentId.value = item.id;
  result.value = { request: item.request, plan: item.plan };
  lastQuery.value = item.query;
  window.location.hash = "/plan";
}

function removeSavedTrip(id: string) {
  history.value = deleteSavedTrip(id);
  if (currentId.value === id) {
    currentId.value = "";
    result.value = null;
    lastQuery.value = "";
  }
}

function persistEditedPlan(plan: TripPlan) {
  if (!currentId.value) return;
  history.value = updateSavedTripPlan(currentId.value, plan);
}

function downloadCurrent() {
  const item = history.value.find((saved) => saved.id === currentId.value);
  if (item) downloadTrip(item);
}

function printPlan() {
  window.print();
}
</script>

<template>
  <div class="site-shell">
    <nav class="site-nav" aria-label="Main navigation">
      <a href="#/" :class="{ active: !isPlan && !isHistory }">&#24320;&#22987;&#35268;&#21010;</a>
      <a href="#/history" :class="{ active: isHistory }">
        &#25105;&#30340;&#26053;&#34892;&#35745;&#21010; <span v-if="history.length">{{ history.length }}</span>
      </a>
    </nav>

    <main v-if="!isPlan && !isHistory">
      <section id="planner" class="hero">
        <img class="hero-illustration" src="/hero-landmarks.svg" alt="" aria-hidden="true" />
        <div class="hero-content">
          <h1>&#19979;&#19968;&#31449;&#65292;<em>&#21435;&#21738;&#37324;&#65311;</em></h1>
          <p class="hero-lead">
            &#21578;&#35785;&#25105;&#20204;&#20320;&#24819;&#21435;&#21738;&#12289;&#20309;&#26102;&#20986;&#21457;&#21644;&#21916;&#27426;&#20160;&#20040;&#12290;
          </p>
          <PlanForm
            :loading="loading"
            :error="error"
            :missing-fields="missingFields"
            @submit="generate"
            @edit="clearPromptState"
          />
        </div>
      </section>

      <section id="features" class="info-section">
        <div class="info-heading">
          <span class="section-kicker">WHY PLAN WITH US</span>
          <h2>&#20174;&#24819;&#27861;&#65292;&#21040;&#30475;&#24471;&#35265;&#30340;&#26053;&#31243;</h2>
          <p>&#36755;&#20837;&#26053;&#34892;&#38656;&#27714;&#25110;&#30452;&#25509;&#36873;&#25321;&#26085;&#26399;&#65292;&#35268;&#21010;&#22120;&#20250;&#25972;&#29702;&#36335;&#32447;&#12289;&#20303;&#23487;&#12289;&#22825;&#27668;&#21644;&#36153;&#29992;&#21442;&#32771;&#12290;</p>
        </div>
        <div class="feature-grid">
          <article class="feature-card"><span class="feature-number">01</span><h3>&#20449;&#24687;&#19981;&#20840;&#20250;&#36861;&#38382;</h3><p>&#32570;&#23569;&#30446;&#30340;&#22320;&#12289;&#20986;&#21457;&#26085;&#26399;&#25110;&#36820;&#31243;&#26085;&#26399;&#26102;&#65292;&#20808;&#35831;&#20320;&#34917;&#20805;&#65292;&#19981;&#25897;&#33258;&#29468;&#27979;&#12290;</p></article>
          <article class="feature-card"><span class="feature-number">02</span><h3>&#36880;&#26085;&#23433;&#25490;&#26356;&#28165;&#26970;</h3><p>&#26597;&#30475;&#27599;&#22825;&#30340;&#26223;&#28857;&#12289;&#39184;&#39278;&#19982;&#20303;&#23487;&#24314;&#35758;&#65292;&#24182;&#22312;&#22320;&#22270;&#19978;&#20102;&#35299;&#34892;&#31243;&#20301;&#32622;&#12290;</p></article>
          <article class="feature-card"><span class="feature-number">03</span><h3>&#25915;&#30053;&#38543;&#26102;&#25214;&#24471;&#21040;</h3><p>&#29983;&#25104;&#21518;&#33258;&#21160;&#20445;&#23384;&#21040;&#25105;&#30340;&#26053;&#34892;&#35745;&#21010;&#65292;&#36824;&#21487;&#20197;&#19979;&#36733;&#21040;&#26412;&#22320;&#38271;&#26399;&#20445;&#30041;&#12290;</p></article>
        </div>
      </section>
      <section id="how-it-works" class="closing-section">
        <span class="section-kicker">HOW IT WORKS</span>
        <h2>&#35828;&#20986;&#20320;&#30340;&#19979;&#19968;&#27573;&#26053;&#31243;&#12290;</h2>
        <p>&#20889;&#19979;&#30446;&#30340;&#22320;&#65292;&#26085;&#26399;&#21487;&#20197;&#30452;&#25509;&#36873;&#25321;&#65307;&#20154;&#25968;&#12289;&#39044;&#31639;&#19982;&#21916;&#22909;&#21487;&#20197;&#32487;&#32493;&#29992;&#33258;&#28982;&#35821;&#35328;&#25551;&#36848;&#12290;</p>
      </section>
    </main>

    <main v-else-if="isHistory">
      <PlanHistory :items="history" @open="openSavedTrip" @remove="removeSavedTrip" />
    </main>

    <main v-else class="result-page">
      <template v-if="result">
        <div class="result-intro">
          <a class="result-back" href="#/">&larr; &#36820;&#22238;&#39318;&#39029;</a>
          <span class="section-kicker">YOUR ITINERARY</span>
          <div class="result-title-row">
            <h1>&#20320;&#30340; {{ result.request.city }} &#20043;&#26053;&#65292;<em>&#24050;&#23601;&#32490;&#12290;</em></h1>
            <div class="result-actions">
              <button type="button" @click="downloadCurrent">&#19979;&#36733;&#25915;&#30053;</button>
              <button type="button" @click="printPlan">&#25171;&#21360; / &#20445;&#23384; PDF</button>
            </div>
          </div>
          <p class="result-original">&ldquo;{{ lastQuery }}&rdquo;</p>
          <div class="result-facts">
            <span v-if="result.request.origin_city">&#20174; {{ result.request.origin_city }} &#20986;&#21457;</span>
            <span>{{ result.request.start_date }} &mdash; {{ result.request.end_date }}</span>
            <span>{{ result.plan.days.length }} &#22825;&#34892;&#31243;</span>
            <span>{{ result.request.travelers }} &#20154;&#20986;&#34892;</span>
            <span>{{ result.request.budget_level }}&#39044;&#31639;</span>
            <span class="saved-badge">&#24050;&#20445;&#23384;&#21040;&#25105;&#30340;&#26053;&#34892;&#35745;&#21010;</span>
          </div>
        </div>
        <div class="result-content">
          <TripResult :plan="result.plan" @update="persistEditedPlan" />
        </div>
      </template>
      <div v-else class="result-missing">
        <span class="section-kicker">YOUR ITINERARY</span>
        <h1>&#36824;&#27809;&#26377;&#29983;&#25104;&#34892;&#31243;</h1>
        <p>&#22238;&#21040;&#39318;&#39029;&#65292;&#35828;&#35828;&#20320;&#30340;&#26053;&#34892;&#35745;&#21010;&#21543;&#12290;</p>
        <a class="closing-cta" href="#/">&#36820;&#22238;&#39318;&#39029; <span aria-hidden="true">&nearr;</span></a>
      </div>
    </main>

    <footer class="site-footer">
      <p>&#25226;&#26053;&#34892;&#24819;&#27861;&#65292;&#24930;&#24930;&#21464;&#25104;&#35745;&#21010;&#12290;</p>
      <small>AI &#29983;&#25104;&#20869;&#23481;&#21644;&#36153;&#29992;&#20165;&#20379;&#35268;&#21010;&#21442;&#32771;&#65292;&#23454;&#38469;&#23433;&#25490;&#35831;&#20197;&#23448;&#26041;&#20449;&#24687;&#20026;&#20934;&#12290;</small>
    </footer>
  </div>
</template>
