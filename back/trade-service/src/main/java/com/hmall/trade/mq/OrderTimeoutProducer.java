package com.hmall.trade.mq;

import com.hmall.trade.config.OrderMqConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.core.MessagePostProcessor;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 订单超时消息生产者。
 *
 * <p>下单成功后投递一条延迟消息，到期后由 {@link OrderTimeoutListener} 消费：
 * 若订单仍未支付则关闭并回补库存。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class OrderTimeoutProducer {

    private final RabbitTemplate rabbitTemplate;

    /** 支付超时时间，默认 30 分钟；演示时可启动参数覆盖成 10 秒 */
    @Value("${hm.order.timeout-ms:1800000}")
    private long timeoutMs;

    public void send(Long orderId) {
        MessagePostProcessor delay = message -> {
            // x-delay：延迟毫秒数，由 delayed message 插件解析
            message.getMessageProperties().setDelay((int) timeoutMs);
            return message;
        };
        rabbitTemplate.convertAndSend(
                OrderMqConfig.DELAY_EXCHANGE,
                OrderMqConfig.DELAY_ROUTING_KEY,
                String.valueOf(orderId),
                delay
        );
        log.info("订单超时消息已投递 orderId={} delay={}ms", orderId, timeoutMs);
    }
}
