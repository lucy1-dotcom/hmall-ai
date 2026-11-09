package com.hmall.gateway.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.hmall.gateway.domain.AiChatRequest;
import com.hmall.gateway.exception.AiChatException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import javax.validation.Valid;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * AI 对话网关：前端只认 Java，不直接碰 Python。
 *
 * <p>请求链路：
 * <pre>
 * 浏览器 → Nginx /api/chat/send → 网关(本类) → WebClient → Python /api/ai/chat (SSE)
 *        ←────────────── 事件原样回传（流式，边收边发）──────────────
 * </pre>
 *
 * <p>两个路径映射的原因：Nginx 的 {@code location /api} 会把 {@code /api} 前缀 rewrite 掉，
 * 所以到网关时是 {@code /chat/send}；直接调网关时才是 {@code /api/chat/send}。
 * 两种写法都支持，避免依赖调用方从哪进来。</p>
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class AiChatController {

    /** SSE 事件里的 data 是字符串（Python 侧已经是 JSON 文本） */
    private static final ParameterizedTypeReference<ServerSentEvent<String>> SSE_TYPE =
            new ParameterizedTypeReference<ServerSentEvent<String>>() {
            };

    private final WebClient aiWebClient;
    private final ObjectMapper objectMapper;

    @PostMapping(
            value = {"/chat/send", "/api/chat/send"},
            produces = MediaType.TEXT_EVENT_STREAM_VALUE
    )
    public Flux<ServerSentEvent<String>> send(@Valid @RequestBody AiChatRequest request) {
        log.info("AI 对话转发 user_id={}, session_id={}", request.getUserId(), request.getSessionId());

        return aiWebClient.post()
                .uri("/api/ai/chat")
                .contentType(MediaType.APPLICATION_JSON)
                .accept(MediaType.TEXT_EVENT_STREAM)
                .bodyValue(request)
                .retrieve()
                // Python 侧参数校验失败/未配置密钥时会返回 4xx/5xx 的普通 JSON
                .onStatus(HttpStatus::isError, response ->
                        response.bodyToMono(String.class)
                                .defaultIfEmpty("")
                                .flatMap(body -> Mono.error(
                                        new AiChatException(response.statusCode().value(), body))))
                // 逐帧解码成 ServerSentEvent，再原样往下游写，天然保持流式
                .bodyToFlux(SSE_TYPE)
                // 流一旦开始就改不了 HTTP 状态码了，只能把错误作为事件推给前端
                .onErrorResume(this::toErrorEvent);
    }

    private Flux<ServerSentEvent<String>> toErrorEvent(Throwable ex) {
        String message;
        if (ex instanceof AiChatException) {
            AiChatException aiEx = (AiChatException) ex;
            log.warn("AI 服务返回错误 status={} body={}", aiEx.getStatus(), aiEx.getMessage());
            message = "AI 服务返回错误：" + aiEx.getMessage();
        } else {
            log.error("AI 服务不可用", ex);
            message = "AI 服务不可用：" + ex.getMessage();
        }
        return Flux.just(ServerSentEvent.builder(toJson(Map.of("type", "error", "message", message))).build());
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            Map<String, Object> fallback = new LinkedHashMap<>();
            fallback.put("type", "error");
            fallback.put("message", "AI 服务异常");
            return "{\"type\":\"error\",\"message\":\"AI 服务异常\"}";
        }
    }
}
