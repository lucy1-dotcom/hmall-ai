package com.hmall.trade.config;

import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.CustomExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.HashMap;
import java.util.Map;

/**
 * 订单超时关闭用到的 RabbitMQ 拓扑。
 *
 * <p>用的是<b>延迟消息插件</b> {@code rabbitmq_delayed_message_exchange}：
 * 交换机类型为 {@code x-delayed-message}，发送时在消息头里写 {@code x-delay}（毫秒），
 * RabbitMQ 到点后才把消息投递到队列。</p>
 *
 * <p>为什么不用「TTL + 死信队列」：DLX 方案在同一个队列里不同 TTL 的消息会出现
 * <b>队头阻塞</b>（先到的长 TTL 消息不投递，后面短 TTL 的也走不了），
 * 需要按 TTL 分队列，维护成本高。延迟插件直接按消息维度定时，语义更直观。</p>
 */
@Configuration
public class OrderMqConfig {

    /** 延迟交换机 */
    public static final String DELAY_EXCHANGE = "trade.delay.exchange";
    /** 超时订单队列 */
    public static final String DELAY_QUEUE = "trade.order.delay.queue";
    /** 路由键 */
    public static final String DELAY_ROUTING_KEY = "order.delay";

    @Bean
    public CustomExchange orderDelayExchange() {
        Map<String, Object> args = new HashMap<>(2);
        // 延迟交换机本质是个“按 x-delay 延时的 direct 交换机”
        args.put("x-delayed-type", "direct");
        return new CustomExchange(DELAY_EXCHANGE, "x-delayed-message", true, false, args);
    }

    @Bean
    public Queue orderDelayQueue() {
        return new Queue(DELAY_QUEUE, true);
    }

    @Bean
    public Binding orderDelayBinding() {
        return BindingBuilder.bind(orderDelayQueue())
                .to(orderDelayExchange())
                .with(DELAY_ROUTING_KEY)
                .noargs();
    }
}
