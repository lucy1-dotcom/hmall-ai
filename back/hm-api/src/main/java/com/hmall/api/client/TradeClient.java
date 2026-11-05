package com.hmall.api.client;

import io.swagger.annotations.ApiImplicitParam;
import io.swagger.annotations.ApiOperation;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;

@FeignClient(value = "trade-service")
public interface TradeClient {
    @ApiOperation("标记订单已支付")
    @ApiImplicitParam(name = "orderId", value = "订单id", paramType = "path")
    @PutMapping("/orders/{orderId}")
    void markOrderPaySuccess(@PathVariable("orderId") Long orderId);
}
