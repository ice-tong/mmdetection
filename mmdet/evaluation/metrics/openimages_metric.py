# Copyright (c) OpenMMLab. All rights reserved.
import warnings
from typing import Sequence

import numpy as np
from mmengine.logging import print_log
from mmeval import OIDMeanAP
from terminaltables import AsciiTable

from mmdet.registry import METRICS


@METRICS.register_module()
class OpenImagesMetric(OIDMeanAP):
    """A wrapper of :class:`mmeval.OIDMeanAP`.

    This wrapper implements the `process` method that parses predictions and
    labels from inputs. This enables ``mmengine.Evaluator`` to handle the data
    flow of different tasks through a unified interface.

    In addition, this wrapper also implements the ``evaluate`` method that
    parses metric results and print pretty table of metrics per class.

    Args:
        dist_backend (str | None): The name of the distributed communication
            backend. Refer to :class:`mmeval.BaseMetric`.
            Defaults to 'torch_cuda'.
        **kwargs: Keyword parameters passed to :class:`mmeval.OIDMeanAP`.
    """

    def __init__(self, dist_backend: str = 'torch_cuda', **kwargs) -> None:
        ioa_thrs = kwargs.pop('ioa_thrs', None)
        if ioa_thrs is not None and 'iof_thrs' not in kwargs:
            kwargs['iof_thrs'] = ioa_thrs
            warnings.warn(
                'DeprecationWarning: The `ioa_thrs` parameter of '
                '`OpenImagesMetric` is deprecated, use `iof_thrs` instead!')

        collect_device = kwargs.pop('collect_device', None)
        if collect_device is not None:
            warnings.warn(
                'DeprecationWarning: The `collect_device` parameter of '
                '`OpenImagesMetric` is deprecated, use `dist_backend` instead.'
            )  # noqa: E501

        super().__init__(
            classwise_result=True, dist_backend=dist_backend, **kwargs)

    # TODO: data_batch is no longer needed, consider adjusting the
    #  parameter position
    def process(self, data_batch: dict, data_samples: Sequence[dict]) -> None:
        """Process one batch of data samples and predictions.

        Parse predictions and ground truths from ``data_samples`` and invoke
        ``self.add``.

        Args:
            data_batch (dict): A batch of data from the dataloader.
            data_samples (Sequence[dict]): A batch of data samples that
                contain annotations and predictions.
        """
        predictions, groundtruths = [], []
        for data_sample in data_samples:
            pred = {
                'bboxes': data_sample['pred_instances']
                ['bboxes'].cpu().numpy(),  # noqa: E501
                'scores': data_sample['pred_instances']
                ['scores'].cpu().numpy(),  # noqa: E501
                'labels':
                data_sample['pred_instances']['labels'].cpu().numpy()
            }
            predictions.append(pred)

            gt = {
                'instances': data_sample['instances'],
                'image_level_labels': data_sample.get('image_level_labels',
                                                      None),  # noqa: E501
            }
            groundtruths.append(gt)

        self.add(predictions, groundtruths)

    def evaluate(self, *args, **kwargs) -> dict:
        """Returns metric results and print pretty table of metrics per class.

        This method would be invoked by ``mmengine.Evaluator``.
        """
        metric_results = self.compute(*args, **kwargs)
        self.reset()

        classwise_result = metric_results['classwise_result']
        del metric_results['classwise_result']

        classes = self.dataset_meta['CLASSES']
        header = ['class', 'gts', 'dets', 'recall', 'ap']

        for i, (iou_thr,
                iof_thr) in enumerate(zip(self.iou_thrs,
                                          self.iof_thrs)):  # noqa: E501
            for j, scale_range in enumerate(self.scale_ranges):
                table_title = f' IoU thr: {iou_thr} IoF thr: {iof_thr} '
                if scale_range != (None, None):
                    table_title += f'Scale range: {scale_range} '

                table_data = [header]
                aps = []
                for k in range(len(classes)):
                    class_results = classwise_result[k]
                    recalls = class_results['recalls'][i, j]
                    recall = 0 if len(recalls) == 0 else recalls[-1]
                    row_data = [
                        classes[k], class_results['num_gts'][i, j],
                        class_results['num_dets'],
                        round(recall, 3),
                        round(class_results['ap'][i, j], 3)
                    ]
                    table_data.append(row_data)
                    if class_results['num_gts'][i, j] > 0:
                        aps.append(class_results['ap'][i, j])

                mean_ap = np.mean(aps) if aps != [] else 0
                table_data.append(['mAP', '', '', '', f'{mean_ap:.3f}'])
                table = AsciiTable(table_data, title=table_title)
                table.inner_footing_row_border = True
                print_log('\n' + table.table, logger='current')

        evaluate_results = {
            f'openimages/{k}': round(float(v), 3)
            for k, v in metric_results.items()
        }
        return evaluate_results
