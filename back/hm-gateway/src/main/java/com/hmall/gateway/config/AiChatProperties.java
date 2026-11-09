package com.hmall.gateway.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Python AI 服务的连接配置。
 *
 * <p>注意 serviceUrl 写的是「服务名」而不是 IP：网关用 @LoadBalanced 的 WebClient
 * 去 Nacos 查实例，所以换机器、换端口、多实例扩容都不用改配置。</p>
 */
@Data
@Component
@ConfigurationProperties(prefix = "hm.ai")
public class AiChatProperties {

    /** AI 服务地址；lb 模式下是 http://服务名 */
    private String serviceUrl = "http://hmall-ai";

    /** 建连超时（毫秒）。只设连接超时，不设读超时，否则长回答会被掐断 */
    private int connectTimeoutMs = 3000;

    /** 响应超时（秒）。流式场景下指两次数据之间的最大间隔 */
    private int responseTimeoutSeconds = 180;
}
