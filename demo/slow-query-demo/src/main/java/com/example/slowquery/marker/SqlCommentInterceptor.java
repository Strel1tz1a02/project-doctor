package com.example.slowquery.marker;

import org.apache.ibatis.executor.Executor;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.mapping.ParameterMapping;
import org.apache.ibatis.mapping.SqlSource;
import org.apache.ibatis.plugin.Interceptor;
import org.apache.ibatis.plugin.Intercepts;
import org.apache.ibatis.plugin.Invocation;
import org.apache.ibatis.plugin.Plugin;
import org.apache.ibatis.plugin.Signature;
import org.apache.ibatis.session.ResultHandler;
import org.apache.ibatis.session.RowBounds;

import java.util.Map;
import java.util.Properties;

/**
 * 为每条 MyBatis SQL 前置 {@code /* pd:<仓库相对路径>:<行号> request=<32 位十六进制 ID> *&#47;}
 * 标记，供 Project Doctor 的 performance_schema 探针把 SQL 归属到请求与代码位置。
 *
 * <p>标记约定见平台文档 docs/development/acceptance/2026-10-02-fix-results.md。注解式
 * Mapper 没有 XML 行号，这里用 Mapper 源文件中各 {@code @Select} 的行号作为代码位置。
 * 没有请求关联（未带请求头）或未知语句时不做标记，避免产生无法归属的旧标记。
 */
@Intercepts({
    @Signature(type = Executor.class, method = "query",
            args = {MappedStatement.class, Object.class, RowBounds.class, ResultHandler.class}),
    @Signature(type = Executor.class, method = "update",
            args = {MappedStatement.class, Object.class})
})
public class SqlCommentInterceptor implements Interceptor {

    private static final String MAPPER_PATH =
            "src/main/java/com/example/slowquery/mapper/OrderMapper.java";
    private static final Map<String, Integer> LINES = Map.of(
            "findSlowOrders", 14,
            "countSlowOrders", 29,
            "findUserById", 40
    );

    @Override
    public Object intercept(Invocation invocation) throws Throwable {
        String requestId = RequestContext.getRequestId();
        if (requestId == null) {
            return invocation.proceed();
        }

        MappedStatement statement = (MappedStatement) invocation.getArgs()[0];
        Object parameter = invocation.getArgs()[1];
        String method = statement.getId().substring(statement.getId().lastIndexOf('.') + 1);
        Integer line = LINES.get(method);
        if (line == null) {
            return invocation.proceed();
        }

        BoundSql boundSql = statement.getBoundSql(parameter);
        String comment = "/* pd:" + MAPPER_PATH + ":" + line + " request=" + requestId + " */ ";
        BoundSql commented = new BoundSql(
                statement.getConfiguration(),
                comment + boundSql.getSql(),
                boundSql.getParameterMappings(),
                parameter);
        for (ParameterMapping mapping : boundSql.getParameterMappings()) {
            String prop = mapping.getProperty();
            if (boundSql.hasAdditionalParameter(prop)) {
                commented.setAdditionalParameter(prop, boundSql.getAdditionalParameter(prop));
            }
        }
        invocation.getArgs()[0] = copyFrom(statement, new BoundSqlSource(commented));
        return invocation.proceed();
    }

    private MappedStatement copyFrom(MappedStatement source, SqlSource sqlSource) {
        MappedStatement.Builder builder = new MappedStatement.Builder(
                source.getConfiguration(), source.getId(), sqlSource, source.getSqlCommandType());
        builder.resource(source.getResource());
        builder.fetchSize(source.getFetchSize());
        builder.statementType(source.getStatementType());
        builder.keyGenerator(source.getKeyGenerator());
        if (source.getKeyProperties() != null && source.getKeyProperties().length > 0) {
            builder.keyProperty(String.join(",", source.getKeyProperties()));
        }
        builder.timeout(source.getTimeout());
        builder.parameterMap(source.getParameterMap());
        builder.resultMaps(source.getResultMaps());
        builder.resultSetType(source.getResultSetType());
        builder.cache(source.getCache());
        builder.flushCacheRequired(source.isFlushCacheRequired());
        builder.useCache(source.isUseCache());
        return builder.build();
    }

    @Override
    public Object plugin(Object target) {
        return Plugin.wrap(target, this);
    }

    @Override
    public void setProperties(Properties properties) {
    }

    /** 固定返回已改写的 BoundSql 的 SqlSource。 */
    private static final class BoundSqlSource implements SqlSource {
        private final BoundSql boundSql;

        BoundSqlSource(BoundSql boundSql) {
            this.boundSql = boundSql;
        }

        @Override
        public BoundSql getBoundSql(Object parameterObject) {
            return boundSql;
        }
    }
}
