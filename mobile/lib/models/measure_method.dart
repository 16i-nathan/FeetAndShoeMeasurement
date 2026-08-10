class MeasureMethod {
  const MeasureMethod({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.dos,
    required this.donts,
    required this.checklist,
    required this.guideAsset,
    this.needsDepthHardware = false,
  });

  final String id;
  final String title;
  final String subtitle;
  final String icon; // emoji sparingly avoided — use Material icon name key
  final List<String> dos;
  final List<String> donts;
  final List<String> checklist;
  final String guideAsset;
  final bool needsDepthHardware;
}

const paperMethod = MeasureMethod(
  id: 'paper',
  title: 'A4 paper',
  subtitle: 'Foot on a full blank A4 sheet — production mode',
  icon: 'description',
  guideAsset: 'assets/guides/rgb_guide.png',
  dos: [
    'Entire A4 sheet visible (all four corners)',
    'Foot fully on the paper (toes to heel)',
    'Phone parallel to the floor (true top-down)',
    'Dark non-white floor, soft even light, flash off',
  ],
  donts: [
    'Paper corners cut off',
    'Angled / perspective shot',
    'Flash glare or hard shadows',
    'White floor (hard to see paper)',
  ],
  checklist: [
    'Top-down',
    'Full A4 in frame',
    'Foot on paper',
    'No flash',
    'Dark floor',
  ],
);

const labMethods = <MeasureMethod>[
  MeasureMethod(
    id: 'card',
    title: 'Credit card',
    subtitle: 'Lab only — card beside the foot',
    icon: 'credit_card',
    guideAsset: 'assets/guides/rgb_guide.png',
    dos: [
      'Top-down photo, phone parallel to the floor',
      'Full foot visible (toes to heel)',
      'Full credit card visible, flat, not covering the foot',
      'Dark floor, even soft light, flash off',
    ],
    donts: [
      'Cropped card or foot at the edge',
      'Sideways / angled camera',
      'Flash glare on the floor',
      'White or shiny floor',
    ],
    checklist: [
      'Top-down',
      'Full foot + full card',
      'No flash',
      'Dark floor',
      'No clutter',
    ],
  ),
  MeasureMethod(
    id: 'both',
    title: 'Paper + card',
    subtitle: 'Lab only — paper ROI, card scale',
    icon: 'layers',
    guideAsset: 'assets/guides/rgb_guide.png',
    dos: [
      'Full A4 visible with foot on it',
      'Credit card on/near the paper, fully visible',
      'Top-down, soft light',
    ],
    donts: [
      'Missing paper corners',
      'Card covered or cropped',
      'Angled shot or flash glare',
    ],
    checklist: [
      'Full A4',
      'Full card',
      'Top-down',
      'No flash',
      'Dark floor',
    ],
  ),
  MeasureMethod(
    id: 'depth',
    title: 'Depth / LiDAR',
    subtitle: 'Lab only — LiDAR/AR depth phones',
    icon: 'view_in_ar',
    guideAsset: 'assets/guides/depth_guide.png',
    needsDepthHardware: true,
    dos: [
      'Overhead camera, parallel to floor',
      'Entire foot inside the frame',
      'One foot only on a clear floor',
      'Soft light, flash off',
      'Matte floor (not shiny tile)',
    ],
    donts: [
      'Cropped toes or heel',
      'Side angle',
      'Cables, shoes, or clutter beside the foot',
      'Harsh shadows / flash',
      'Shiny reflective floor (breaks LiDAR)',
    ],
    checklist: [
      'Overhead',
      'Full foot',
      'Clear floor',
      'Soft light',
      'No flash',
      'No shiny floor',
      'Depth saved automatically',
    ],
  ),
];

/// Production list is A4-only unless LAB_MODES=true at build time.
List<MeasureMethod> methodsForBuild({required bool labModes}) {
  if (labModes) {
    return [paperMethod, ...labMethods];
  }
  return [paperMethod];
}

MeasureMethod methodById(String id) {
  final all = [paperMethod, ...labMethods];
  return all.firstWhere((m) => m.id == id, orElse: () => paperMethod);
}
