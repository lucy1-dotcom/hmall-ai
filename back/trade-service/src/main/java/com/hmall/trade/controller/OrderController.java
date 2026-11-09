package com.hmall.trade.controller;

import com.alibaba.csp.sentinel.annotation.SentinelResource;
import com.alibaba.csp.sentinel.slots.block.BlockException;
import com.hmall.common.exception.CommonException;
import com.hmall.common.utils.BeanUtils;
import com.hmall.trade.domain.dto.OrderFormDTO;
import com.hmall.trade.domain.vo.OrderVO;
import com.hmall.trade.mq.OrderTimeoutProducer;
import com.hmall.trade.service.IOrderService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiImplicitParam;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.ibatis.annotations.Param;
import org.springframework.web.bind.annotation.*;

@Api(tags = "订单管理接口")
@Slf4j
@RestController
@RequestMapping("/orders")
@RequiredArgsConstructor
public class OrderController {
    private final IOrderService orderService;
    private final OrderTimeoutProducer orderTimeoutProducer;

    @ApiOperation("根据id查询订单")
    @GetMapping("{id}")
    public OrderVO queryOrderById(@Param ("订单id")@PathVariable("id") Long orderId) {
        return BeanUtils.copyBean(orderService.getById(orderId), OrderVO.class);
    }

    @ApiOperation("创建订单")
    @PostMapping
    @SentinelResource(
            value = "createOrder",
            blockHandler = "createOrderBlocked",
            fallback = "createOrderFallback",
            // 业务异常（库存不足等）不算熔断指标，只有下游故障才触发降级
            exceptionsToIgnore = CommonException.class
    )
    public Long createOrder(@RequestBody OrderFormDTO orderFormDTO){
        Long orderId = orderService.createOrder(orderFormDTO);
        // 事务在 service 方法返回时已提交，这里再投递延迟消息：
        // 万一下单回滚了，不会留下一条“假超时”消息去关一个不存在的订单
        orderTimeoutProducer.send(orderId);
        return orderId;
    }

    /** 被限流 / 熔断打开时兜底 */
    public Long createOrderBlocked(OrderFormDTO orderFormDTO, BlockException ex) {
        log.warn("下单被限流或熔断：{}", ex.getRule());
        throw new CommonException("当前下单人数过多，请稍后重试", 429);
    }

    /** 下游服务异常时降级（例如商品服务不可用） */
    public Long createOrderFallback(OrderFormDTO orderFormDTO, Throwable ex) {
        log.error("下单降级，商品服务可能不可用", ex);
        throw new CommonException("订单服务暂时不可用，请稍后重试", 503);
    }

    @ApiOperation("标记订单已支付")
    @ApiImplicitParam(name = "orderId", value = "订单id", paramType = "path")
    @PutMapping("/{orderId}")
    public void markOrderPaySuccess(@PathVariable("orderId") Long orderId) {
        orderService.markOrderPaySuccess(orderId);
    }
}
