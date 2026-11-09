package com.hmall.trade.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.hmall.trade.domain.dto.OrderFormDTO;
import com.hmall.trade.domain.po.Order;

/**
 * <p>
 *  服务类
 * </p>
 *
 * @author 虎哥
 * @since 2023-05-05
 */
public interface IOrderService extends IService<Order> {

    Long createOrder(OrderFormDTO orderFormDTO);

    void markOrderPaySuccess(Long orderId);

    /**
     * 关闭超时未支付的订单并回补库存（幂等）。
     *
     * @return true 表示本次确实关闭了订单
     */
    boolean closeUnpaidOrder(Long orderId);
}
