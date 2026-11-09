package com.hmall.gateway.config;

import io.netty.channel.ChannelOption;
import lombok.RequiredArgsConstructor;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;

/**
 * 专门给 AI 服务用的 WebClient。
 *
 * <p>三个关键点：
 * 1) {@code @LoadBalanced}：URL 里的 host 会被当成服务名，交给 Nacos 服务发现解析，
 *    所以配置里写 {@code http://hmall-ai} 而不是 {@code http://localhost:8000}；
 * 2) 只设连接超时、不设读超时，否则长回答会被掐断；
 * 3) 加大内存缓冲上限，避免大帧被截断。</p>
 */
@Configuration
@RequiredArgsConstructor
public class WebClientConfig {

    private final AiChatProperties properties;

    /**
     * 带负载均衡能力的 Builder。{@code @LoadBalanced} 本身带 @Qualifier 语义，
     * 所以下面注入时能精确拿到这一个，不会和 Spring Boot 默认的 Builder 冲突。
     */
    @Bean
    @LoadBalanced
    public WebClient.Builder aiWebClientBuilder() {
        return WebClient.builder();
    }

    @Bean
    public WebClient aiWebClient(@LoadBalanced WebClient.Builder builder) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, properties.getConnectTimeoutMs())
                .responseTimeout(Duration.ofSeconds(properties.getResponseTimeoutSeconds()));

        return builder
                .baseUrl(properties.getServiceUrl())
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .codecs(cfg -> cfg.defaultCodecs().maxInMemorySize(1024 * 1024))
                .build();
    }
}
