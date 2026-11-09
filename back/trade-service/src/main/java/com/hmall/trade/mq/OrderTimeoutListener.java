package com.hmall.trade.mq;

import com.hmall.trade.config.OrderMqConfig;
import com.hmall.trade.service.IOrderService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

/**
 * 订单超时消费者。
 *
 * <p>幂等由 {@link IOrderService#closeUnpaidOrder} 保证：
 * 用「status=1 → 5」的条件更新，只有更新成功的那个消费者才会回补库存，
 * 和支付回调并发时也不会重复回补或误关已支付订单。</p>
 *
 * <p>消费失败会抛出异常，由配置里的 retry + default-requeue-rejected=false
 * 控制：重试 3 次后丢弃，不会无限重入队列打满 CPU。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class OrderTimeoutListener {

    private final IOrderService orderService;

    @RabbitListener(queues = OrderMqConfig.DELAY_QUEUE)
    public void onOrderTimeout(String payload) {
        Long orderId = Long.valueOf(payload);
        log.info("收到订单超时消息 orderId={}", orderId);
        boolean closed = orderService.closeUnpaidOrder(orderId);
        log.info("订单超时处理完成 orderId={} 结果={}", orderId,
                closed ? "已关闭并回补库存" : "跳过（订单不存在/已支付/已关闭）");
    }
}
