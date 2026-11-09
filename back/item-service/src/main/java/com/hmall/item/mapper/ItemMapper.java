package com.hmall.item.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.hmall.api.dto.OrderDetailDTO;
import com.hmall.item.domain.po.Item;
import org.apache.ibatis.annotations.Update;

/**
 * <p>
 * 商品表 Mapper 接口
 * </p>
 *
 * @author 虎哥
 * @since 2023-05-05
 */
public interface ItemMapper extends BaseMapper<Item> {

    /** 扣减库存（下单时） */
    @Update("UPDATE item SET stock = stock - #{num} WHERE id = #{itemId}")
    void updateStock(OrderDetailDTO orderDetail);

    /**
     * 回补库存（订单超时关闭 / 取消时）。
     *
     * <p>单独写一条 SQL 而不是给 {@link #updateStock} 传负数：语义清晰，
     * 以后要加“不能超过原始库存”之类的约束也好扩展。</p>
     */
    @Update("UPDATE item SET stock = stock + #{num} WHERE id = #{itemId}")
    void restoreStock(OrderDetailDTO orderDetail);
}
