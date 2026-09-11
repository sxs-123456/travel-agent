<script setup lang="ts">
import { ref } from "vue";
import { message } from "ant-design-vue";
import type { RagQueryResponse } from "@/types/rag";
import { queryKnowledge } from "@/api/client";

const question = ref("");
const loading = ref(false);
const result = ref<RagQueryResponse | null>(null);

async function onAsk() {
  const q = question.value.trim();
  if (!q) return;
  loading.value = true;
  result.value = null;
  try {
    result.value = await queryKnowledge(q);
  } catch (e: any) {
    message.error(formatError(e, "问答失败，请稍后再试"));
  } finally {
    loading.value = false;
  }
}

function formatError(e: any, fallback: string): string {
  const m = e?.message;
  if (typeof m === "string" && m && !m.includes("[object")) return m;
  return fallback;
}

function pct(score?: number | null) {
  if (score == null) return 0;
  return Math.min(100, Math.round(score * 100));
}
</script>

<template>
  <div class="tp-card">
    <div class="tp-section-title">📚 旅行知识问答（RAG）</div>
    <p class="tp-muted" style="font-size: 12px; margin-bottom: 10px">
      基于本地向量知识库检索增强回答（Pexels 图源与行程规划之外的独立能力），回答附带引用来源与相似度。
      若提问的城市/主题知识库尚未收录，会自动切换为「通用知识」模式并诚实标注，不会答非所问。
    </p>

    <div style="display: flex; gap: 8px">
      <a-input
        v-model:value="question"
        placeholder="如：故宫门票多少钱？"
        style="flex: 1"
        @press-enter="onAsk"
      />
      <a-button type="primary" :loading="loading" @click="onAsk">提问</a-button>
    </div>

    <div v-if="loading" class="tp-muted" style="margin-top: 14px">
      正在检索知识库并生成回答…
    </div>

    <div v-if="result" style="margin-top: 14px">
      <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px">
        <span
          v-if="result.from_kb === false"
          style="
            font-size: 11px;
            color: #b76e00;
            background: #fff7e6;
            border: 1px solid #ffe7ba;
            border-radius: 10px;
            padding: 1px 10px;
          "
        >🌐 通用知识（知识库未收录，以下为模型通用建议）</span>
        <span
          v-else
          style="
            font-size: 11px;
            color: #237804;
            background: #f6ffed;
            border: 1px solid #b7eb8f;
            border-radius: 10px;
            padding: 1px 10px;
          "
        >✅ 来自知识库</span>
      </div>
      <div
        style="
          background: #f6f8fb;
          border-radius: 8px;
          padding: 12px 14px;
          font-size: 13px;
          line-height: 1.7;
          white-space: pre-wrap;
        "
      >
        {{ result.answer }}
      </div>

      <div v-if="result.sources.length" style="margin-top: 12px">
        <div class="tp-muted" style="font-size: 12px; margin-bottom: 8px">引用来源</div>
        <div
          v-for="(s, i) in result.sources"
          :key="i"
          style="
            border: 1px solid #f0f0f0;
            border-radius: 8px;
            padding: 10px 12px;
            margin-bottom: 8px;
          "
        >
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span style="font-size: 12px; font-weight: 500">📄 {{ s.source }}</span>
            <span style="font-size: 11px; color: #2f6bff">相似度 {{ pct(s.score) }}%</span>
          </div>
          <a-progress
            :percent="pct(s.score)"
            :show-info="false"
            size="small"
            style="margin: 4px 0"
            :stroke-color="'#2f6bff'"
          />
          <div class="tp-muted" style="font-size: 11px">{{ s.snippet }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
