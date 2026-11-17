package com.hmall.trade.controller;

import com.hmall.common.exception.BadRequestException;
import com.hmall.common.exception.ForbiddenException;
import com.hmall.trade.domain.po.Order;
import com.hmall.trade.service.IOrderService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 给 Python AI 服务（hmall-ai）的 Agent 用的订单查询接口。
 *
 * <p>接口路径按 AI 侧的约定固定为 {@code /api/order/latest}，
 * 网关里配了对应的路由和鉴权白名单。</p>
 *
 * @author hmall
 */
@Api(tags = "订单智能助理接口")
@RestController
@RequestMapping("/api/order")
@RequiredArgsConstructor
public class OrderAgentController {

    private final IOrderService orderService;

    @ApiOperation("查询用户最近一笔订单")
    @GetMapping("/latest")
    public Map<String, Object> queryLatestOrder(@RequestParam("userId") Long userId) {
        Order order = orderService.lambdaQuery()
                .eq(Order::getUserId, userId)
                .orderByDesc(Order::getCreateTime)
                .last("limit 1")
                .one();

        Map<String, Object> result = new LinkedHashMap<>();
        if (order == null) {
            // 没有订单也返回 200，让 AI 侧好处理（工具里判断 orderId 是否为空即可）
            result.put("orderId", null);
            result.put("status", "暂无订单");
            return result;
        }
        result.put("orderId", order.getId());
        result.put("status", statusText(order.getStatus()));
        result.put("statusCode", order.getStatus());
        result.put("totalFee", order.getTotalFee());
        result.put("createTime", order.getCreateTime());
        return result;
    }

    /**
     * 取消订单（AI 助理专用）。
     *
     * <p>这条接口只会被「用户确认后的待办动作」调用，不会由模型直接触发：
     * Agent 侧先用工具生成一个待确认动作，用户点确认后才请求这里。</p>
     *
     * <p>两处校验：订单必须属于该用户；只有待支付（status=1）的订单能被关闭，
     * 具体由 {@code closeUnpaidOrder} 用条件更新兜底，并发支付也不会误关。</p>
     */
    @ApiOperation("取消待支付订单（AI 助理在用户确认后调用）")
    @PutMapping("/{orderId}/cancel")
    public Map<String, Object> cancelOrder(
            @PathVariable("orderId") Long orderId,
            @RequestParam("userId") Long userId) {
        Order order = orderService.getById(orderId);
        if (order == null) {
            throw new BadRequestException("订单不存在");
        }
        if (!userId.equals(order.getUserId())) {
            throw new ForbiddenException("无权操作该订单");
        }

        boolean closed = orderService.closeUnpaidOrder(orderId);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("orderId", orderId);
        result.put("cancelled", closed);
        result.put("message", closed ? "订单已取消，库存已回补" : "订单当前状态不允许取消（可能已支付或已关闭）");
        return result;
    }

    /**
     * 把库里的数字状态翻译成人话，AI 直接转述即可。
     */
    private String statusText(Integer status) {
        if (status == null) {
            return "未知";
        }
        switch (status) {
            case 1:
                return "待支付";
            case 2:
                return "已支付，待发货";
            case 3:
                return "已发货";
            case 4:
                return "已确认收货";
            case 5:
                return "已关闭";
            case 6:
                return "已完成";
            default:
                return "未知(" + status + ")";
        }
    }
}
